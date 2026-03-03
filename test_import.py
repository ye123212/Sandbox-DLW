import sys
import traceback

try:
    import backend.app.main
    print("Success")
except Exception as e:
    with open("err.txt", "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    print("Error written to err.txt")
