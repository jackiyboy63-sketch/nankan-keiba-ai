import io,json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from nar_site_publish import deliver,attempt_delivery,SITE

class Response:
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return json.dumps(self.body).encode()

class Client:
    def __init__(self):self.requests=[]
    def open(self,req,timeout):
        self.requests.append((req,timeout))
        return Response({'count':1,'duplicate':False,'id':'receipt'})

class Tests(unittest.TestCase):
    def test_not_configured_does_not_read_or_send(self):
        with patch('nar_site_publish.build_batch') as build:
            self.assertEqual(deliver('unused',environ={}),{'status':'not_configured'});build.assert_not_called()
    def test_credentials_only_sent_to_fixed_private_site(self):
        for url in ['https://example.com',SITE+'.example.com',SITE+'?redirect=x']:
            c=Client()
            with self.assertRaises(ValueError):deliver('unused',opener=c,environ={'NANKAN_SITE_URL':url,'NANKAN_SITE_TOKEN':'test-secret'})
            self.assertEqual(c.requests,[])
    def test_success_sends_json_and_checks_acknowledgement(self):
        b={'kind':'ratings','source':'test','records':[{'date':'2026-10-28','race':1}]};c=Client()
        with patch('nar_site_publish.build_batch',return_value=b):r=deliver('unused',opener=c,environ={'NANKAN_SITE_URL':SITE,'NANKAN_SITE_TOKEN':'test-secret'})
        self.assertEqual(r['status'],'delivered');req,timeout=c.requests[0];self.assertEqual(req.full_url,SITE+'/api/records');self.assertEqual(json.loads(req.data),b);self.assertEqual(timeout,10)
    def test_failed_delivery_does_not_fail_saved_prediction_or_reveal_secret(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('nar_site_publish.deliver',side_effect=ValueError('test-secret')),patch('builtins.print') as log:
                r=attempt_delivery(root)
            self.assertEqual(r,{'status':'failed','error_type':'ValueError'});self.assertNotIn('test-secret',Path(root,'site_delivery.json').read_text());self.assertNotIn('test-secret',str(log.call_args))
    def test_invalid_receipt_is_not_success(self):
        c=Client();c.open=lambda *a,**k:Response({'error':'not saved'})
        with patch('nar_site_publish.build_batch',return_value={'records':[]}):
            with self.assertRaises(ValueError):deliver('unused',opener=c,environ={'NANKAN_SITE_URL':SITE,'NANKAN_SITE_TOKEN':'test-secret'})
if __name__=='__main__':unittest.main()
