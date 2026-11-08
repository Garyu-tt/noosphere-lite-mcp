"""Operator-bound process isolation and adversarial MCP tool argument tests."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from noosphere_lite.__main__ import config, bound_project, reject_bound_path_overrides
from noosphere_lite.mcp_server import run, _bound_scope
from noosphere_lite.vault import MemoryVault, VaultError


class _CapturedMCP:
    instance = None

    def __init__(self, name):
        assert name == "noosphere-lite-mcp"
        self.tools = {}
        self.started = False
        type(self).instance = self

    def tool(self):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register

    def run(self, transport):
        assert transport == "stdio"
        self.started = True


def capture_tools(vault, project):
    """Exercise the exact registered tool functions without starting stdio."""
    root = types.ModuleType("mcp")
    root.__path__ = []
    server = types.ModuleType("mcp.server")
    server.__path__ = []
    modern = types.ModuleType("mcp.server.mcpserver")
    modern.MCPServer = _CapturedMCP
    with patch.dict(sys.modules, {"mcp":root, "mcp.server":server,
                                  "mcp.server.mcpserver":modern}):
        run(vault, bound_project=project)
    assert _CapturedMCP.instance.started
    return _CapturedMCP.instance.tools


class BoundProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.base_env={
            "NSL_PRIMARY":str(self.root/"d1"),
            "NSL_MIRROR":str(self.root/"d2"),
            "NSL_KEY_FILE":str(self.root/"secrets"/"key"),
        }

    def make(self,project):
        with patch.dict(os.environ,{**self.base_env,"NSL_BOUND_PROJECT":project}):
            p1,p2,key=config()
            self.assertEqual(bound_project(),project)
        vault=MemoryVault(p1,p2,key,allow_same_device=True)
        vault.initialize()
        return vault,(p1,p2,key),capture_tools(vault,project)

    def test_separate_encrypted_journals_and_keys_by_project(self):
        a,paths_a,ta=self.make("alpha")
        b,paths_b,tb=self.make("beta")
        for x,y in zip(paths_a,paths_b):
            self.assertNotEqual(x,y)
        self.assertNotEqual(paths_a[2].read_bytes(),paths_b[2].read_bytes())
        own=ta["memory_add"]("Private alpha data","EXCLUSIVELYALPHACONTENT")
        other=tb["memory_add"]("Private beta data","EXCLUSIVELYBETACONTENT")
        self.assertEqual([x["id"] for x in ta["memory_search"]("Private")],[own["id"]])
        self.assertEqual([x["id"] for x in tb["memory_search"]("Private")],[other["id"]])
        self.assertEqual(ta["memory_read"](own["id"])["tags"],["project:alpha"])
        with self.assertRaises(VaultError):
            ta["memory_read"](other["id"])
        with self.assertRaises(VaultError):
            ta["memory_link"](own["id"],other["id"])
        with self.assertRaises(VaultError):
            ta["memory_neighborhood"](other["id"])
        self.assertEqual(ta["memory_status"]()["bound_project"],"alpha")
        self.assertEqual(tb["memory_status"]()["bound_project"],"beta")
        self.assertTrue(paths_a[0].joinpath("journal.nlv").exists())
        self.assertTrue(paths_b[1].joinpath("journal.nlv").exists())

    def test_scoped_mcp_cannot_widen_evidence_or_project_filters(self):
        vault,paths,tools=self.make("alpha")
        tools["memory_add"]("Alpha plan","ALPHAPLAN",source="file:a",tags=["planning"],kind="decision")
        for tags in (["project:beta"],["planning","project:beta"]):
            with self.assertRaisesRegex(VaultError,"cross-project"):
                tools["memory_add"]("Forged","FORGED",tags=tags)
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_context"]("ALPHAPLAN",scope="beta")
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_briefing"]("beta")
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_by_source"]("beta","file:a")
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_evidence_source_add"]("x",'{"v":"secret"}',scope="beta")
        source=tools["memory_evidence_source_add"]("x",'{"v":"alpha"}')["id"]
        claim=tools["memory_evidence_propose"]("x.value",source,"/v")["id"]
        facts=tools["memory_evidence_context"]("x.value")["facts"]
        self.assertEqual(facts[0]["claim_id"],claim)
        self.assertEqual(facts[0]["value"],"alpha")
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_evidence_context"]("x.value",scope="beta")
        with self.assertRaisesRegex(VaultError,"requested project"):
            tools["memory_evidence_propose"]("x.value",source,"/v",scope="beta")
        self.assertEqual(len(tools["memory_briefing"]("alpha")["records"]),1)
        self.assertEqual(len(tools["memory_by_source"]("alpha","file:a")["records"]),1)
        self.assertFalse(tools["memory_search"]("FORGED"))
        self.assertTrue(tools["memory_context"]("ALPHAPLAN")["memories"])

    def test_config_refuses_path_traversal_and_explicit_override(self):
        for name in ("","../beta","a/beta"," spaced","x"*49,"alpha\\0evil"):
            with self.subTest(name=name):
                with patch.dict(os.environ,{**self.base_env,"NSL_BOUND_PROJECT":name}):
                    with self.assertRaises(VaultError):
                        config()
        with patch.dict(os.environ,self.base_env,clear=True):
            p1,p2,key=config()
            self.assertEqual(p1,Path(self.base_env["NSL_PRIMARY"]))
            self.assertEqual(key,Path(self.base_env["NSL_KEY_FILE"]))
        with self.assertRaisesRegex(VaultError,"forbids explicit"):
            reject_bound_path_overrides("alpha",primary=self.root/"beta")
        with self.assertRaisesRegex(VaultError,"forbids explicit"):
            reject_bound_path_overrides("alpha",key_file=self.root/"beta"/"key")
        reject_bound_path_overrides(None,primary=self.root/"legacy")

    def test_bound_runtime_rejects_shared_unscoped_vault(self):
        unsafe=MemoryVault(self.root/"shared-a",self.root/"shared-b",
                           self.root/"shared-key",allow_same_device=True)
        unsafe.initialize()
        with self.assertRaisesRegex(VaultError,"bound MCP requires distinct"):
            capture_tools(unsafe,"alpha")

    def test_bound_scope_is_not_caller_widenable(self):
        self.assertEqual(_bound_scope("default","alpha"),"alpha")
        self.assertEqual(_bound_scope("alpha","alpha"),"alpha")
        self.assertEqual(_bound_scope("beta",None),"beta")
        for v in ("beta","",None,"alpha/../beta"):
            with self.assertRaises(VaultError):
                _bound_scope(v,"alpha")

if __name__=="__main__":
    unittest.main()

