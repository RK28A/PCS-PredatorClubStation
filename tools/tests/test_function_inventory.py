import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import function_inventory
import nid_names
import progress


class InventoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, relative, text):
        file = self.root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")

    def library(self, name, source):
        self.write(f"core/libs/prx/{name}/Export.cpp", source)

    def rows(self):
        rows, shared, empty = function_inventory.collect(self.root)
        return {(row["library"], row["name"]): row for row in rows}, shared, empty

    def test_every_state_and_category_is_assigned_from_the_sources(self):
        self.library("libkernel", (
            "int APS5_VABI sceKernelTested(int handle) { return Lookup(handle); }\n"
            "int APS5_VABI sceKernelUntested(int handle, void* out) { return Fill(handle, out); }\n"
            "int APS5_VABI sceKernelGap(int handle) { return Close(handle); }\n"
            "int APS5_VABI sceKernelInert() { return 0; }\n"
            "int APS5_VABI sceKernelPending() { NotImplemented_nid_no_patch(__func__); }\n"
            "int APS5_VABI libkernelUnknown_AAAAAAAAAAA_nid_no_patch() { NotImplemented_nid_no_patch(__func__); }\n"
            'APS5_EXPORT("AAAAAAAAAAA", libkernelUnknown_AAAAAAAAAAA_nid_no_patch);\n'
        ))
        self.write("core/libs/prx/libkernel/tests/Tested.cpp", "int main() { return sceKernelTested(1); }\n")
        self.write("docs/dev/debt/libkernel.md", "- sceKernelGap returns before the descriptor is flushed.\n")
        rows, shared, empty = self.rows()
        self.assertEqual(shared, {})
        self.assertEqual(empty, [])
        categories = {name: row["category"] for (_, name), row in rows.items()}
        self.assertEqual(categories, {
            "sceKernelTested": "implemented_tested",
            "sceKernelUntested": "implemented_untested",
            "sceKernelGap": "implemented_documented_gap",
            "sceKernelInert": "inert",
            "sceKernelPending": "pending",
            "libkernelUnknown_AAAAAAAAAAA": "pending_unknown_name",
        })
        tested = rows["libkernel", "sceKernelTested"]
        self.assertEqual((tested["result"], tested["parameters"], tested["signature_known"], tested["tests"]), ("int", "int handle", "yes", 1))
        self.assertEqual(tested["nid"], nid_names.compute_nid("sceKernelTested"))
        self.assertEqual(tested["nid_source"], "computed from the name")
        unknown = rows["libkernel", "libkernelUnknown_AAAAAAAAAAA"]
        self.assertEqual((unknown["nid"], unknown["nid_source"], unknown["signature_known"]), ("AAAAAAAAAAA", "explicit", "no"))
        self.assertEqual(rows["libkernel", "sceKernelPending"]["signature_known"], "no")
        self.assertEqual(rows["libkernel", "sceKernelInert"]["signature_known"], "yes")

    def test_counts_match_the_progress_scanner(self):
        self.library("libSceExample", (
            "int APS5_VABI sceExampleOpen(int id) { return Open(id); }\n"
            "int APS5_VABI sceExampleClose_nid_postfix(int id) { return Close(id); }\n"
            "int APS5_VABI sceExampleHelper_nid_no_patch(int id) { return id; }\n"
            "int APS5_VABI sceExampleLater() { NotImplemented_nid_no_patch(__func__); }\n"
        ))
        rows, _, _ = self.rows()
        group = progress.scan_library(self.root / "core/libs/prx/libSceExample")
        self.assertEqual(sum(1 for row in rows.values() if row["state"] != "pending"), group["done"])
        self.assertEqual(sum(1 for row in rows.values() if row["state"] == "pending"), group["todo"])
        self.assertEqual(sorted(name for _, name in rows), ["sceExampleClose", "sceExampleLater", "sceExampleOpen"])
        self.assertEqual(rows["libSceExample", "sceExampleClose"]["nid"], nid_names.compute_nid("sceExampleClose"))

    def test_a_standard_name_gets_the_library_reference_and_a_sony_name_does_not(self):
        self.library("libc", (
            "int APS5_VABI strcmp_nid_postfix(const char* a, const char* b) { return Compare(a, b); }\n"
            "int APS5_VABI sceLibcHeapGetTraceInfo(void* info) { return Trace(info); }\n"
        ))
        self.library("libSceNpManager", "int APS5_VABI sceNpGetState(int user, int* state) { return State(user, state); }\n")
        rows, _, _ = self.rows()
        standard = rows["libc", "strcmp"]
        self.assertEqual((standard["reference"], standard["console_needed"]), ("ISO C, POSIX and FreeBSD libc", "no"))
        sony = rows["libc", "sceLibcHeapGetTraceInfo"]
        self.assertEqual((sony["reference"], sony["console_needed"]), ("", "yes"))
        network = rows["libSceNpManager", "sceNpGetState"]
        self.assertEqual((network["proprietary"], network["console_needed"]), ("PlayStation Network or system service", "yes"))
        self.assertEqual(standard["importance"], "core: reached by ordinary titles")

    def test_tests_of_other_trees_and_library_sources_do_not_count_as_tests(self):
        self.library("libSceExample", (
            "int APS5_VABI sceExampleOpen(int id) { return Open(id); }\n"
            "int APS5_VABI sceExampleUse(int id) { return sceExampleOpen(id); }\n"
        ))
        self.write("tools/tests/test_other.py", "name = 'sceExampleOpen'\n")
        rows, _, _ = self.rows()
        self.assertEqual(rows["libSceExample", "sceExampleOpen"]["tests"], 0)
        self.assertEqual(rows["libSceExample", "sceExampleOpen"]["category"], "implemented_untested")

    def test_wrapper_and_empty_libraries_are_listed_apart(self):
        self.library("libSceOwner", "int APS5_VABI sceOwnerOpen(int id) { return Open(id); }\n")
        self.write("core/libs/prx/libSceOwner/Owner.cmake", "set(ownerSources Export.cpp)\n")
        self.write("core/libs/prx/libSceWrapper/CMakeLists.txt", "include(${CMAKE_CURRENT_SOURCE_DIR}/../libSceOwner/Owner.cmake)\n")
        self.library("libSceEmpty", "APS5_DUMMY_FUN\n")
        rows, shared, empty = self.rows()
        self.assertEqual(shared, {"libSceWrapper": "libSceOwner"})
        self.assertEqual(empty, ["libSceEmpty"])
        self.assertEqual([library for library, _ in rows], ["libSceOwner"])

    def test_command_line_writes_the_rows_and_a_summary_that_add_up(self):
        self.library("libSceExample", (
            "int APS5_VABI sceExampleOpen(int id) { return Open(id); }\n"
            "int APS5_VABI sceExampleNothing() { return 0; }\n"
            "int APS5_VABI sceExampleLater() { NotImplemented_nid_no_patch(__func__); }\n"
        ))
        table, summary = self.root / "inventory.csv", self.root / "inventory.json"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(function_inventory.main(["--root", str(self.root), "--csv", str(table), "--json", str(summary)]), 0)
        with open(table, encoding="utf-8", newline="") as handle:
            written = list(csv.DictReader(handle))
        self.assertEqual([row["name"] for row in written], ["sceExampleNothing", "sceExampleOpen", "sceExampleLater"])
        data = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(data["functions"], 3)
        self.assertEqual(data["states"], {"implemented": 1, "inert": 1, "pending": 1})
        self.assertEqual(sum(data["categories"].values()), data["functions"])
        self.assertEqual(data["by_library"]["libSceExample"]["states"], {"implemented": 1, "inert": 1, "pending": 1})
        self.assertEqual(data["by_library"]["libSceExample"]["categories"]["pending"], 1)
        self.assertIn("functions 3: implemented 1, inert 1, pending 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
