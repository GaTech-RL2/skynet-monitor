import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
import server

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        server.allowed_hosts={'127.0.0.1:'+str(cls.http.server_port)}
        server.access_key='synthetic-test-key-not-a-real-key'
        server.state={'data':{'jobs':[]},'error':None,'refreshing':False}
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()

    def test_login_and_authenticated_snapshot(self):
        jar=__import__('http.cookiejar',fromlist=['CookieJar']).CookieJar()
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req=urllib.request.Request(self.base+'/login',data=urllib.parse.urlencode({'key':server.access_key}).encode())
        with client.open(req) as r:self.assertIn(b'Running jobs',r.read())
        with client.open(self.base+'/api/snapshot') as r:self.assertEqual(json.load(r)['data']['jobs'],[])

    def test_no_api_without_auth(self):
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(self.base+'/api/snapshot')
        self.assertEqual(e.exception.code,401)

    def test_unknown_job_not_accessible(self):
        req=urllib.request.Request(self.base+'/api/job/999',headers={'Cookie':'skynet_access='+server.access_key})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,404)

    def test_host_validation(self):
        req=urllib.request.Request(self.base,headers={'Host':'untrusted.example'})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,403)
