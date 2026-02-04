#!/usr/bin/env python3
import sys
import smtplib


host, port, user, password, to_email = sys.argv[1:6]

try:
    # Тест соединения
    print(f"Тестирую {host}:{port}...")
    server = smtplib.SMTP(host, int(port), timeout=10)
    server.set_debuglevel(1)
    
    
    print("EHLO...")
    server.ehlo()
    
    
    print("STARTTLS...")
    server.starttls()
    
    
    print(f"Логин {user}...")
    server.login(user, password)
    
    
    message = f"From: {user}\nTo: {to_email}\nSubject: SMTP Test\n\nTest message"
    server.sendmail(user, to_email, message)
    
    server.quit()
    print("SUCCESS!")
    
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
