import unittest
import numpy as np
from nar_calibration_compare import apply_calibration,choose
class CalibrationTests(unittest.TestCase):
    def test_sigmoid_identity(self):
        p=np.array([.1,.3,.6]);q=apply_calibration(p,['a']*3,{'family':'sigmoid_normalized','intercept':0,'slope':1})
        np.testing.assert_allclose(q,p)
    def test_sum_and_order_preserved(self):
        p=np.array([.1,.3,.6,.2,.8]);keys=['a']*3+['b']*2
        q=apply_calibration(p,keys,{'family':'sigmoid_normalized','intercept':2,'slope':.5})
        self.assertAlmostEqual(q[:3].sum(),1);self.assertAlmostEqual(q[3:].sum(),1)
        self.assertTrue(q[0]<q[1]<q[2]);self.assertTrue(q[3]<q[4])
    def test_mixture(self):
        q=apply_calibration(np.array([.1,.9]),['a','a'],{'family':'uniform_mixture','strength':.2})
        np.testing.assert_allclose(q,[.18,.82])
    def test_invalid_input_rejected(self):
        for p in [[.2,.2],[0,1],[float('nan'),.5]]:
            with self.assertRaises(ValueError):apply_calibration(p,['a','a'],{'family':'original'})
    def test_selection_minimizes_only_supplied_calibration_loss(self):
        best,trials=choose(np.array([.1,.9,.8,.2]),np.array([1,0,0,1]),['a','a','b','b'])
        self.assertEqual(best['calibration_log_loss'],min(t['calibration_log_loss'] for t in trials))
        self.assertEqual(best,choose(np.array([.1,.9,.8,.2]),np.array([1,0,0,1]),['a','a','b','b'])[0])
if __name__=='__main__':unittest.main()
