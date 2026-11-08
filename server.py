import http.server
import urllib.request
import urllib.parse
import ssl
import json
import re
import concurrent.futures
import os

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
            
            # HTML ট্যাগ মুছে ফেলা
            clean_html = re.sub(r'<[^>]+>', ' ', html)
            combined = f"{subject} \n {text} \n {clean_html}"
            
            # এক্সট্রা স্পেস এবং নতুন লাইন মুছে ফেলা
            combined = re.sub(r'\s+', ' ', combined)
            
            # নাম্বারের মাঝখানে স্পেস থাকলে তা মুছে ফেলা (যেমন: 2769 1303 -> 27691303)
            combined = re.sub(r'(?<=\d)\s+(?=\d)', '', combined)

            # ১. "Confirmation code" বা "Use code" এর ঠিক পরের কোডটি খোঁজা (সবচেয়ে নির্ভুল)
            match = re.search(r'(?:Confirmation code|Use code|Login code|Verification code)[^\d]{0,15}?(\d{4,8})', combined, re.IGNORECASE)
            if match: 
                return match.group(1)

            # ২. ইনস্টাগ্রামের স্টাইল: "27691303 is your Instagram confirmation code"
            match = re.search(r'\b(\d{6,8})\b is your', combined, re.IGNORECASE)
            if match: 
                return match.group(1)

            # ৩. সাধারণ 'code' বা 'otp' শব্দের পরের কোড (যেখানে অন্তত ১টি নাম্বার থাকতে হবে)
            for match in re.finditer(r'(?:code|otp|pin|verification|passcode|login)[^\w]*((?=[A-Z0-9]*\d)[A-Z0-9]{4,8})', combined, re.IGNORECASE):
                code = match.group(1).upper()
                if code not in ['2023', '2024', '2025', '2026', '94025', '12345']:
                    return code

            # ৪. ৮ ডিজিটের কোড (মেটা পাসওয়ার্ড রিসেট)
            matches = re.findall(r'\b\d{8}\b', combined)
            for m in matches:
                if m not in ['20231012', '20231112', '94025']: 
                    return m

            # ৫. ৬ ডিজিটের কোড (মেটা লগইন)
            matches = re.findall(r'\b\d{6}\b', combined)
            for m in matches:
                if m not in ['202310', '202311', '202312', '94025']: 
                    return m
                    
            # ৬. ৫ ডিজিটের কোড (94025 strictly বাদ দেওয়া হলো)
            matches = re.findall(r'\b\d{5}\b', combined)
            for m in matches:
                if m not in ['12345', '94025']: 
                    return m

            # ৭. ৪ ডিজিটের কোড
            matches = re.findall(r'\b\d{4}\b', combined)
            for m in matches:
                if m not in ['2023', '2024', '2025', '2026', '94025']: 
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
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), MyHandler) as httpd:
        print(f"✅ সার্ভার চালু হয়েছে! পোর্ট: {PORT}")
        httpd.serve_forever()
