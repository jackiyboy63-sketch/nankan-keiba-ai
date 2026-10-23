import unittest,tempfile,json,hashlib
from pathlib import Path
from nar_run_store import read_run,list_runs,FILES

class StoreTests(unittest.TestCase):
    def save(self,root):
        folder=root/'2026-10-23/20-01/test';folder.mkdir(parents=True)
        hashes={}
        for name in FILES:
            raw=b'horse_no,score\n1,50\n';(folder/name).write_bytes(raw);hashes[name]=hashlib.sha256(raw).hexdigest()
        (folder/'run_manifest.json').write_text(json.dumps({'status':'completed_prerace','files':hashes}))
        return folder
    def test_valid_saved_output(self):
        with tempfile.TemporaryDirectory() as t:
            f=self.save(Path(t));m,data=read_run(f);self.assertEqual(len(data),3);self.assertEqual(len(list_runs(t)),1)
    def test_changed_output_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            f=self.save(Path(t));(f/'ratings.csv').write_text('changed')
            with self.assertRaisesRegex(ValueError,'変わ'):read_run(f)
    def test_failed_run_not_read_as_success(self):
        with tempfile.TemporaryDirectory() as t:
            f=self.save(Path(t));(f/'run_manifest.json').write_text('{"status":"failed"}')
            with self.assertRaises(ValueError):read_run(f)
    def test_unknown_path_in_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            f=self.save(Path(t));(f/'run_manifest.json').write_text('{"status":"completed_prerace","files":{"../secret":"x"}}')
            with self.assertRaises(ValueError):read_run(f)
