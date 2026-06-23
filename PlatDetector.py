import cv2
import pytesseract
import re
import time
import os
from datetime import datetime

# HAPUS TANDA PAGAR (#) PADA BARIS DI BAWAH INI
# Pastikan path ini sesuai dengan lokasi instalasi Tesseract di komputer Anda
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# PENTING UNTUK WINDOWS: Hapus tanda pagar (#) di bawah ini dan sesuaikan dengan lokasi Tesseract Anda
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class LicensePlateDetector:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)
        self.plate_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_russian_plate_number.xml')
        
        self.last_saved_text = ""
        self.last_saved_time = 0
        
        # 1. BUAT FOLDER UNTUK MENYIMPAN FOTO
        self.folder_simpan = "foto_plat"
        if not os.path.exists(self.folder_simpan):
            os.makedirs(self.folder_simpan)
            
        print("Sistem Dimulai. Menunggu plat terdeteksi...")

    def run(self):
        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 2. SENSITIVITAS DITINGKATKAN (scaleFactor 1.05, minNeighbors 3)
            # Agar lebih mudah menangkap kotak plat nomor
            plates = self.plate_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30))

            for (x, y, w, h) in plates:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                
                # Potong gambar area plat saja
                plate_img = frame[y:y+h, x:x+w]
                
                # Coba scan teks (OCR)
                text = self.extract_text(plate_img)
                
                # Jika gagal scan atau terlalu pendek, tandai sebagai UNKNOWN
                if not text or len(text) < 3:
                    text = "UNKNOWN"
                
                # Logika Cooldown: Hindari jepret plat yang sama berkali-kali dalam 5 detik
                current_time = time.time()
                if text != self.last_saved_text or (current_time - self.last_saved_time > 5):
                    self.save_data_and_image(text, plate_img)
                    self.last_saved_text = text
                    self.last_saved_time = current_time

                # Tampilkan hasil scan di layar kamera
                if text != "UNKNOWN":
                    cv2.putText(frame, text, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)

            cv2.imshow('Pendeteksi Plat Kendaraan', frame)
            
            if cv2.waitKey(1) & 0xFF == 27: # Tekan 'Esc' untuk keluar
                break
                
        self.cap.release()
        cv2.destroyAllWindows()

    def extract_text(self, img):
        # Preprocessing gambar untuk Tesseract
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.bilateralFilter(gray, 11, 17, 17)
        _, thresh = cv2.threshold(blur, 150, 255, cv2.THRESH_BINARY)
        
        text = pytesseract.image_to_string(thresh, config='--psm 8')
        clean_text = re.sub(r'[^A-Z0-9]', '', text.upper()) # Ambil huruf dan angka saja
        return clean_text

    def save_data_and_image(self, text, img):
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        # 3. SIMPAN FOTO KE DALAM FOLDER
        nama_file_foto = f"{self.folder_simpan}/{timestamp_str}_{text}.jpg"
        cv2.imwrite(nama_file_foto, img)
        
        # 4. SIMPAN DATA KE CSV
        with open("data_plat.csv", "a") as f:
            f.write(f"{timestamp_str},{text},{nama_file_foto}\n")
            
        print(f"[{timestamp_str}] Terdeteksi: {text} | Foto tersimpan di: {nama_file_foto}")

if __name__ == "__main__":
    app = LicensePlateDetector()
    app.run()