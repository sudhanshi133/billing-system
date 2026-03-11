#!/usr/bin/env python3
import tkinter as tk
from PIL import Image, ImageTk

print("Creating root window...")
root = tk.Tk()
root.title("Test")
root.geometry("400x300")

print("Creating label...")
label = tk.Label(root, text="Hello World", font=('Arial', 20))
label.pack(pady=50)

print("Starting mainloop...")
root.mainloop()
print("Done!")

