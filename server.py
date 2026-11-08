import http.server
import urllib.request
import urllib.parse
import ssl
import json
import re
import concurrent.futures
import os # Render-এর পোর্ট নেওয়ার জন্য

# Render এর জন্য পোর্ট ডাইনামিক করা হলো
PORT = int(os.environ.get("PORT", 9999)) 
MAILPIT_URL = "http://mail.tplink.info"

def extract_code_for_msg(msg_id):
    try:
        req = urllib.request.Request(f"{MAILPIT_URL}/api/v1/message/{msg_id}", headers={'Accept': 'application/json'})
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=context) as resp:
            msg_data = json.loads(resp.read().decode('utf-8'))
            subject = msg_data.get('Subject', '')
            text = msg_data.get('Text', '')
            html = msg_data.get('HTML', '')
            
            clean_html = re.sub(r'<[^>]+>', ' ', html)
            combined = f"{subject} \n {text} \n {clean_html}"
            combined = re.sub(r'\s+', ' ', combined)
            
            matches = re.findall(r'\b\d{6}\b', combined)
            for m in matches:
                if m not in ['2023', '2024', '2025', '2026']: return m

            matches = re.findall(r'\b\d{5}\b', combined)
            for m in matches:
                if m not in ['12345']: return m
                
            matches = re.findall(r'\b\d{4}\b', combined)
            for m in matches:
                if m not in ['2023', '2024', '2025', '2026', '1234']: return m
                    
            matches = re.findall(r'\b\d{3}\s\d{3}\b', combined)
            if matches:
                return matches[0].replace(' ', '')
                    
            match = re.search(r'(?:code|otp|pin|verification|passcode|password|login)[^\w]*([a-zA-Z0-9]{4,8})', combined, re.IGNORECASE)
            if match: 
                return match.group(1).upper()
                
            matches = re.findall(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{4,8}\b', combined)
            for m in matches:
                if m not in ['2023', '2024', '2025', '2026']:
                    return m
    except Exception as e:
        pass
    return None

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/search'):
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            user_query = query_params.get('q', [''])[0]
            limit = query_params.get('limit', ['100'])[0]
            start = query_params.get('start', ['0'])[0]

            if user_query:
                target_url = f"{MAILPIT_URL}/api/v1/search?query={urllib.parse.quote(user_query)}&limit={limit}&start={start}"
            else:
                target_url = f"{MAILPIT_URL}/api/v1/messages?limit={limit}&start={start}"

            self.fetch_and_process_list(target_url)

        elif self.path.startswith('/api/message'):
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            msg_id = query_params.get('id', [''])[0]

            if msg_id:
                safe_msg_id = urllib.parse.quote(msg_id)
                target_url = f"{MAILPIT_URL}/api/v1/message/{safe_msg_id}"
                self.fetch_and_send(target_url)
            else:
                self.send_error(400, "Message ID is missing")
        else:
            super().do_GET()

    def fetch_and_process_list(self, target_url):
        try:
            req = urllib.request.Request(target_url, headers={'Accept': 'application/json'})
            context = ssl._create_unverified_context()
            
            with urllib.request.urlopen(req, timeout=30, context=context) as response:
                data = json.loads(response.read().decode('utf-8'))
                messages = data.get('messages', [])
                
                if messages:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
                        future_to_msg = {executor.submit(extract_code_for_msg, msg['ID']): msg for msg in messages}
                        for future in concurrent.futures.as_completed(future_to_msg):
                            msg = future_to_msg[future]
                            try:
                                code = future.result()
                                if code:
                                    msg['ExtractedCode'] = code
                            except Exception:
                                pass

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
        except Exception as e:
             print(f"[ERROR] ❌ {e}")
             self.send_response(500)
             self.end_headers()
             self.wfile.write(f'{{"error": "{str(e)}"}}'.encode())

    def fetch_and_send(self, target_url):
        try:
            req = urllib.request.Request(target_url, headers={'Accept': 'application/json'})
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=context) as response:
                data = response.read()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'{{"error": "{str(e)}"}}'.encode())

if __name__ == "__main__":
    # Render এর জন্য 0.0.0.0 হোস্ট করা জরুরি
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), MyHandler) as httpd:
        print(f"✅ সার্ভার চালু হয়েছে! পোর্ট: {PORT}")
        httpd.serve_forever()
