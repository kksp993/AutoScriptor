from AutoScriptor import *
import traceback
from test_toast import countdown

def study():
    countdown(2, 1)

def next_one(idx: int):
    click(B(120,345+75*idx))

def next_page():
    swipe(B(120,645), B(120,365))

def main_loop():
    while True:
        for j in range(100):
            for i in range(5):
                next_one(i)
                study()
            next_page()
    
if __name__ == "__main__":
    try:
        main_loop()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)