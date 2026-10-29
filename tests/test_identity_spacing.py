import unittest
import pandas as pd
from nar_replay_ev import align_entry_keys
class SpacingTests(unittest.TestCase):
    def h(self,keys):return pd.DataFrame({'race_date':['2026-10-27']*len(keys),'horse_key':keys})
    def e(self,key):return pd.DataFrame({'馬番':[1],'horse_key':[key]})
    def test_pedigree_spacing_unique_match(self):
        old='馬|20210506|Omaha Beach|Reggae Rose'
        e=align_entry_keys(self.h([old]),self.e('馬|20210506|OmahaBeach|ReggaeRose'),'2026-10-28')
        self.assertEqual(e.horse_key.iloc[0],old)
    def test_birth_mismatch_not_joined(self):
        key='馬|20210507|OmahaBeach|ReggaeRose'
        e=align_entry_keys(self.h(['馬|20210506|Omaha Beach|Reggae Rose']),self.e(key),'2026-10-28')
        self.assertEqual(e.horse_key.iloc[0],key)
    def test_parent_mismatch_not_joined(self):
        key='馬|20210506|Other|ReggaeRose'
        e=align_entry_keys(self.h(['馬|20210506|Omaha Beach|Reggae Rose']),self.e(key),'2026-10-28')
        self.assertEqual(e.horse_key.iloc[0],key)
    def test_ambiguous_match_rejected(self):
        h=self.h(['馬|20210506|Omaha Beach|Reggae Rose','馬|20210506|OmahaBeach|Reggae Rose'])
        with self.assertRaises(ValueError):align_entry_keys(h,self.e('馬|20210506|OmahaBeach|ReggaeRose'),'2026-10-28')
    def test_future_identity_not_used(self):
        h=self.h(['馬|20210506|Omaha Beach|Reggae Rose']);h['race_date']='2026-10-29'
        key='馬|20210506|OmahaBeach|ReggaeRose'
        self.assertEqual(align_entry_keys(h,self.e(key),'2026-10-28').horse_key.iloc[0],key)
if __name__=='__main__':unittest.main()
