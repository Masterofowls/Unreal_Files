"""Tests for Tools/ue_asset_audit.py and Tools/ue_asset_audit_export.py.

Runs without Unreal: the exporter is executed against a fake `unreal` module
that mimics the Asset Registry API it uses, on a synthetic project on disk.

    python3 -m unittest discover -s Tools/tests -v
"""
import contextlib
import csv
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
import ue_asset_audit as audit  # noqa: E402

KB = 1024

# Synthetic project: package -> (relative file, size, class, hard deps, soft deps)
PROJECT = {
    "/Game/Maps/L_Main": ("Content/Maps/L_Main.umap", 10 * KB, "World",
                          ["/Game/Chars/BP_Hero", "/Game/Env/SM_Rock", "/Script/Engine"], []),
    "/Game/__ExternalActors__/Maps/L_Main/0/AB/XYZ": ("Content/__ExternalActors__/Maps/L_Main/0/AB/XYZ.uasset", 2 * KB,
                                                      "StaticMeshActor", ["/Game/Env/SM_Tree"], []),
    "/Game/Maps/L_Menu": ("Content/Maps/L_Menu.umap", 5 * KB, "World", ["/Game/UI/W_Menu"], []),
    "/Game/Maps/L_Test": ("Content/Maps/L_Test.umap", 7 * KB, "World", ["/Game/Dev/SM_Debug"], []),
    "/Game/Chars/BP_Hero": ("Content/Chars/BP_Hero.uasset", 20 * KB, "Blueprint",
                            ["/Game/Chars/SK_Hero", "/Engine/BasicShapes/Cube"],
                            ["/Game/Cine/LS_Intro"]),
    "/Game/Chars/SK_Hero": ("Content/Chars/SK_Hero.uasset", 300 * KB, "SkeletalMesh", ["/Game/Chars/T_Hero_D"], []),
    "/Game/Chars/T_Hero_D": ("Content/Chars/T_Hero_D.uasset", 400 * KB, "Texture2D", [], []),
    "/Game/Env/SM_Rock": ("Content/Env/SM_Rock.uasset", 50 * KB, "StaticMesh", ["/Game/Env/Missing_Mat"], []),
    "/Game/Env/SM_Tree": ("Content/Env/SM_Tree.uasset", 60 * KB, "StaticMesh", [], []),
    "/Game/Cine/LS_Intro": ("Content/Cine/LS_Intro.uasset", 900 * KB, "LevelSequence", ["/Game/Cine/T_Big"], []),
    "/Game/Cine/T_Big": ("Content/Cine/T_Big.uasset", 1000 * KB, "Texture2D", [], []),
    "/Game/UI/W_Menu": ("Content/UI/W_Menu.uasset", 30 * KB, "WidgetBlueprint", ["/MyPlugin/Icons/T_Icon"], []),
    "/Game/UI/W_Unused": ("Content/UI/W_Unused.uasset", 15 * KB, "WidgetBlueprint", [], []),
    "/Game/Dev/SM_Debug": ("Content/Dev/SM_Debug.uasset", 80 * KB, "StaticMesh", [], []),
    "/Game/Old/T_Huge": ("Content/Old/T_Huge.uasset", 2000 * KB, "Texture2D", [], []),
    "/Game/Core/BP_GameMode": ("Content/Core/BP_GameMode.uasset", 12 * KB, "Blueprint", ["/Game/Core/DT_Rules"], []),
    "/Game/Core/DT_Rules": ("Content/Core/DT_Rules.uasset", 3 * KB, "DataTable", [], []),
    "/Game/AlwaysCook/DA_Loot": ("Content/AlwaysCook/DA_Loot.uasset", 4 * KB, "DataAsset", [], []),
    "/MyPlugin/Icons/T_Icon": ("Plugins/MyPlugin/Content/Icons/T_Icon.uasset", 8 * KB, "Texture2D", [], []),
}

DEFAULT_ENGINE = """
[/Script/EngineSettings.GameMapsSettings]
GameDefaultMap=/Game/Maps/L_Menu.L_Menu
EditorStartupMap=/Game/Maps/L_Test.L_Test
GlobalDefaultGameMode=/Game/Core/BP_GameMode.BP_GameMode_C
GameInstanceClass=/Script/Engine.GameInstance
"""

DEFAULT_GAME = """
[/Script/UnrealEd.ProjectPackagingSettings]
+MapsToCook=(FilePath="/Game/Maps/L_Main")
+DirectoriesToAlwaysCook=(Path="/Game/AlwaysCook")
+DirectoriesToNeverCook=(Path="/Game/Cine")
"""


def fake_unreal(project_dir, deps):
    """Minimal stand-in for the `unreal` module parts the exporter uses."""
    m = types.ModuleType("unreal")
    m.log = lambda msg: None

    class Paths:
        @staticmethod
        def project_dir():
            return project_dir + "/"

        @staticmethod
        def convert_relative_path_to_full(p):
            return p

        @staticmethod
        def get_project_file_path():
            return os.path.join(project_dir, "MyGame.uproject")

    class Options:
        def __init__(self):
            self.props = {}

        def set_editor_property(self, k, v):
            self.props[k] = v

    class AssetData:
        def __init__(self, cls):
            self.asset_class_path = types.SimpleNamespace(asset_name=cls)

    class Registry:
        def search_all_assets(self, sync):
            pass

        def wait_for_completion(self):
            pass

        def get_assets_by_package_name(self, pkg):
            return [AssetData(deps[pkg][2])] if pkg in deps else []

        def get_dependencies(self, pkg, opts):
            if pkg not in deps:
                return None
            _f, _s, _c, hard, soft = deps[pkg]
            out = []
            if opts.props.get("include_hard_package_references"):
                out += hard
            if opts.props.get("include_soft_package_references"):
                out += soft
            return out or None

    m.Paths = Paths
    m.AssetRegistryDependencyOptions = Options
    m.AssetRegistryHelpers = types.SimpleNamespace(get_asset_registry=lambda: Registry())
    m.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: "5.8.2-test")
    return m


def write_file(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ue_audit_")
        cls.project = os.path.join(cls.tmp, "MyGame").replace("\\", "/")
        for _pkg, (rel, size, _c, _h, _s) in PROJECT.items():
            write_file(os.path.join(cls.project, rel), size)
        # A companion file must be counted with its package.
        write_file(os.path.join(cls.project, "Content/Chars/T_Hero_D.ubulk"), 100 * KB)
        write_file(os.path.join(cls.project, "Plugins/MyPlugin/MyPlugin.uplugin"), 10)
        os.makedirs(os.path.join(cls.project, "Config"))
        with open(os.path.join(cls.project, "Config/DefaultEngine.ini"), "w") as fh:
            fh.write(DEFAULT_ENGINE)
        with open(os.path.join(cls.project, "Config/DefaultGame.ini"), "w") as fh:
            fh.write(DEFAULT_GAME)
        open(os.path.join(cls.project, "MyGame.uproject"), "w").close()

        # Run the exporter against the fake unreal module.
        cls.dump = os.path.join(cls.tmp, "deps.json")
        sys.modules["unreal"] = fake_unreal(cls.project, PROJECT)
        os.environ["UE_ASSET_AUDIT_NO_AUTORUN"] = "1"
        exporter = importlib.import_module("ue_asset_audit_export")
        os.environ["UE_ASSET_AUDIT_OUT"] = cls.dump
        try:
            assert exporter.main() == 0
        finally:
            del os.environ["UE_ASSET_AUDIT_OUT"]
            del sys.modules["unreal"]

        # Fake cooked output: everything except L_Test and the Old folder, plus engine + shader files.
        cls.cooked = os.path.join(cls.tmp, "Saved/Cooked/Windows")
        for pkg, (rel, size, _c, _h, _s) in PROJECT.items():
            if pkg in ("/Game/Maps/L_Test", "/Game/Old/T_Huge"):
                continue
            base = os.path.splitext(os.path.join(cls.cooked, "MyGame", rel))[0]
            ext = ".umap" if rel.endswith(".umap") else ".uasset"
            write_file(base + ext, 1 * KB)
            write_file(base + ".uexp", size // 2)
        write_file(os.path.join(cls.cooked, "Engine/Content/BasicShapes/Cube.uasset"), 1 * KB)
        write_file(os.path.join(cls.cooked, "Engine/Content/BasicShapes/Cube.uexp"), 5 * KB)
        write_file(os.path.join(cls.cooked, "MyGame/Content/ShaderArchive-MyGame-PCD3D_SM6.ushaderbytecode"), 700 * KB)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = audit.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def report(self, *extra):
        path = os.path.join(self.tmp, "rep.json")
        code, out, err = self.run_cli("analyze", self.dump, "--json", path, *extra)
        with open(path) as fh:
            return code, json.load(fh), out

    # ------------------------------------------------------------------ export

    def test_export_dump(self):
        with open(self.dump) as fh:
            data = json.load(fh)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["project_name"], "MyGame")
        self.assertEqual(data["mounts"], {"/Game": "Content", "/MyPlugin": "Plugins/MyPlugin/Content"})
        pk = data["packages"]
        self.assertEqual(set(pk), set(PROJECT))
        self.assertEqual(pk["/Game/Chars/T_Hero_D"]["size"], 500 * KB)  # .uasset + .ubulk
        self.assertIn("Content/Chars/T_Hero_D.ubulk", pk["/Game/Chars/T_Hero_D"]["files"])
        self.assertNotIn("/Script/Engine", pk["/Game/Maps/L_Main"]["hard"])  # code packages filtered
        self.assertEqual(pk["/Game/Chars/BP_Hero"]["soft"], ["/Game/Cine/LS_Intro"])
        self.assertEqual(pk["/Game/Maps/L_Main"]["class"], "World")

    # ------------------------------------------------------------------ levels

    def test_levels_lists_maps_not_external_actors(self):
        code, out, _ = self.run_cli("levels", self.dump, "--closure")
        self.assertEqual(code, 0)
        self.assertIn("/Game/Maps/L_Main", out)
        self.assertNotIn("__ExternalActors__", out)
        self.assertIn("3 maps", out)

    # ------------------------------------------------------------------ analyze

    def test_single_level_closure_includes_wp_actors_and_soft_refs(self):
        code, rep, out = self.report("--levels", "L_Main")
        self.assertEqual(code, 0)
        reach = {a["package"] for a in rep["assets"]}
        expected = {"/Game/Maps/L_Main", "/Game/__ExternalActors__/Maps/L_Main/0/AB/XYZ",
                    "/Game/Chars/BP_Hero", "/Game/Chars/SK_Hero", "/Game/Chars/T_Hero_D",
                    "/Game/Env/SM_Rock", "/Game/Env/SM_Tree", "/Game/Cine/LS_Intro", "/Game/Cine/T_Big"}
        self.assertEqual(reach, expected)
        self.assertEqual({a["package"] for a in rep["assets"] if a["soft_only"]},
                         {"/Game/Cine/LS_Intro", "/Game/Cine/T_Big"})
        self.assertEqual(rep["total_bytes"], sum(PROJECT[p][1] for p in expected) + 100 * KB)
        self.assertIn("/Game/Env/Missing_Mat", rep["missing"])
        self.assertIn("/Engine/BasicShapes/Cube", rep["external_refs"])
        # Largest asset first, with a readable reason.
        self.assertEqual(rep["assets"][0]["package"], "/Game/Cine/T_Big")
        self.assertEqual(rep["assets"][0]["why"], "L_Main -> BP_Hero -> LS_Intro (soft) -> T_Big")
        tree = [x for x in rep["assets"] if x["package"] == "/Game/Env/SM_Tree"][0]
        self.assertEqual(tree["why"], "L_Main[actor XYZ] -> SM_Tree")

    def test_ignore_soft(self):
        _code, rep, _ = self.report("--levels", "/Game/Maps/L_Main", "--soft", "ignore")
        reach = {a["package"] for a in rep["assets"]}
        self.assertNotIn("/Game/Cine/LS_Intro", reach)
        self.assertEqual(rep["soft_only_packages"], 0)

    def test_unused_and_per_level_unique(self):
        _code, rep, _ = self.report("--levels", "L_Main", "L_Menu")
        unused = {u["package"] for u in rep["unused"]}
        self.assertEqual(unused, {"/Game/Maps/L_Test", "/Game/Dev/SM_Debug", "/Game/Old/T_Huge",
                                  "/Game/UI/W_Unused", "/Game/Core/BP_GameMode", "/Game/Core/DT_Rules",
                                  "/Game/AlwaysCook/DA_Loot"})
        menu = [l for l in rep["per_level"] if l["level"].endswith("L_Menu")][0]
        self.assertEqual(menu["packages"], 3)          # map, widget, plugin icon
        self.assertEqual(menu["unique_packages"], 3)
        self.assertEqual(rep["unused_by_folder"][0][0], "/Game/Old")

    def test_from_config_roots_and_never_cook(self):
        _code, rep, out = self.report("--from-config")
        reach = {a["package"] for a in rep["assets"]}
        for pkg in ("/Game/Maps/L_Main", "/Game/Maps/L_Menu", "/Game/Core/BP_GameMode",
                    "/Game/Core/DT_Rules", "/Game/AlwaysCook/DA_Loot"):
            self.assertIn(pkg, reach)
        self.assertNotIn("/Game/Maps/L_Test", reach)       # editor startup map isn't cooked
        self.assertNotIn("/Game/Cine/LS_Intro", reach)     # DirectoriesToNeverCook
        self.assertIn("/Game/Cine/LS_Intro", rep["blocked_by_never_cook"])
        self.assertEqual(rep["config"]["never_dirs"], ["/Game/Cine"])

    def test_budget_and_strict_exit_codes(self):
        code, _rep, _ = self.report("--levels", "L_Main", "--budget-mb", "1")
        self.assertEqual(code, audit.EXIT_BUDGET)
        code, _rep, _ = self.report("--levels", "L_Main", "--budget-mb", "100")
        self.assertEqual(code, audit.EXIT_OK)
        code, _rep, _ = self.report("--levels", "L_Main", "--level-budget-mb", "0.5")
        self.assertEqual(code, audit.EXIT_BUDGET)
        code, _rep, _ = self.report("--levels", "L_Main", "--strict")
        self.assertEqual(code, audit.EXIT_BROKEN)   # Missing_Mat
        code, _rep, _ = self.report("--levels", "L_Menu", "--strict")
        self.assertEqual(code, audit.EXIT_OK)

    def test_cooked_comparison_and_cooked_size_basis(self):
        _code, rep, out = self.report("--levels", "L_Main", "--cooked-dir", self.cooked, "--size", "cooked")
        c = rep["cooked"]
        not_needed = {p for p, _s in c["cooked_but_not_needed"]}
        self.assertIn("/Game/UI/W_Menu", not_needed)
        self.assertIn("/Game/Dev/SM_Debug", not_needed)
        self.assertNotIn("/Game/Chars/SK_Hero", not_needed)
        self.assertNotIn("/Engine/BasicShapes/Cube", not_needed)
        self.assertEqual(c["other_cooked_bytes"], 700 * KB)
        self.assertEqual(c["reachable_but_not_cooked"], [])
        sk = [a for a in rep["assets"] if a["package"] == "/Game/Chars/SK_Hero"][0]
        self.assertEqual(sk["bytes"], 1 * KB + 150 * KB)
        self.assertIn("cooked but NOT needed", out)

    def test_outputs_csv_md_ini(self):
        d = self.tmp
        code, out, err = self.run_cli("analyze", self.dump, "--levels", "L_Main", "L_Menu",
                                      "--csv", d + "/a.csv", "--unused-csv", d + "/u.csv",
                                      "--md", d + "/r.md", "--ini-snippet", d + "/s.ini")
        self.assertEqual(code, 0, err)
        with open(d + "/a.csv") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 12)
        with open(d + "/u.csv") as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 7)
        with open(d + "/r.md") as fh:
            self.assertIn("## Largest included assets", fh.read())
        with open(d + "/s.ini") as fh:
            ini = fh.read()
        self.assertIn('+MapsToCook=(FilePath="/Game/Maps/L_Main")', ini)
        self.assertIn('+MapsToCook=(FilePath="/Game/Maps/L_Menu")', ini)
        self.assertIn(';+DirectoriesToNeverCook=(Path="/Game/Old")', ini)

    def test_level_patterns_and_errors(self):
        levels, errors = audit.resolve_levels(audit.Graph.load(self.dump), ["/Game/Maps/L_M*"])
        self.assertEqual(levels, ["/Game/Maps/L_Main", "/Game/Maps/L_Menu"])
        self.assertEqual(errors, [])
        code, _out, err = self.run_cli("analyze", self.dump, "--levels", "L_Nope")
        self.assertEqual(code, audit.EXIT_ERROR)
        self.assertIn("map not found", err)

    # ------------------------------------------------------------------ why

    def test_why(self):
        code, out, _ = self.run_cli("why", self.dump, "--levels", "L_Main",
                                    "--asset", "/Game/Cine/T_Big.T_Big", "/Game/Old/T_Huge")
        self.assertEqual(code, 0)
        self.assertIn("[only via soft references]", out)
        self.assertIn("soft   /Game/Cine/LS_Intro", out)
        self.assertIn("/Game/Old/T_Huge: NOT included", out)

    # ------------------------------------------------------------------ helpers

    def test_to_package(self):
        self.assertEqual(audit.to_package("/Game/BP.BP_C"), "/Game/BP")
        self.assertEqual(audit.to_package("/Script/Engine.GameMode"), None)
        self.assertEqual(audit.to_package("/Script/Engine.BlueprintGeneratedClass'/Game/X/BP.BP_C'"), "/Game/X/BP")
        self.assertEqual(audit.to_package("None"), None)

    def test_ini_clear_and_remove(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "Config"))
            with open(os.path.join(d, "Config/DefaultGame.ini"), "w") as fh:
                fh.write('[/Script/UnrealEd.ProjectPackagingSettings]\n'
                         '+MapsToCook=(FilePath="/Game/A")\n+MapsToCook=(FilePath="/Game/B")\n'
                         '-MapsToCook=(FilePath="/Game/A")\n')
            self.assertEqual(audit.config_rules(d)["maps"], ["/Game/B"])
            with open(os.path.join(d, "Config/DefaultGame.ini"), "a") as fh:
                fh.write('!MapsToCook=ClearArray\n')
            rules = audit.config_rules(d)
            self.assertEqual(rules["maps"], [])
            self.assertTrue(any("MapsToCook is empty" in n for n in rules["notes"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
