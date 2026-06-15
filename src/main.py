import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gui.app import OCRApp

def main():
    app = OCRApp()
    app.mainloop()

if __name__ == "__main__":
    main()
