import cv2
import numpy as np
from datetime import datetime
import time

class MotionDetectorInstantaneous():
    
    def onChange(self, val): 
        self.threshold = val
    
    def __init__(self, threshold=8, doRecord=True, showWindows=True):
        self.writer = None
        self.doRecord = doRecord 
        self.show = showWindows 
    
        # Inisialisasi kamera
        self.capture = cv2.VideoCapture(0)
        ret, self.frame = self.capture.read()
        
        if not ret:
            raise Exception("Kamera tidak terdeteksi atau tidak dapat diakses.")
            
        self.height, self.width = self.frame.shape[:2]
        
        if doRecord:
            self.initRecorder()
        
        # Frame abu-abu untuk t-1 dan t
        self.frame1gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        self.frame2gray = np.zeros_like(self.frame1gray)
        
        # Array untuk menampung hasil thresholding
        self.res = np.zeros_like(self.frame1gray)
        
        self.nb_pixels = self.width * self.height
        self.threshold = threshold
        self.isRecording = False
        self.trigger_time = 0 
        
        if showWindows:
            cv2.namedWindow("Image")
            cv2.createTrackbar("Detection threshold: ", "Image", self.threshold, 100, self.onChange)
        
    def initRecorder(self):
        codec = cv2.VideoWriter_fourcc(*'MJPG') 
        filename = datetime.now().strftime("%b-%d_%H_%M_%S") + ".avi"
        self.writer = cv2.VideoWriter(filename, codec, 10.0, (self.width, self.height))

    def run(self):
        started = time.time()
        while True:
            ret, curframe = self.capture.read()
            if not ret:
                break
                
            instant = time.time() 
            
            self.processImage(curframe) 
            
            if not self.isRecording:
                if self.somethingHasMoved():
                    self.trigger_time = instant 
                    if instant > started + 5: # Tunggu 5 detik untuk penyesuaian cahaya
                        print(datetime.now().strftime("%b %d, %H:%M:%S"), "- Sesuatu bergerak!")
                        if self.doRecord: 
                            self.isRecording = True
            else:
                if instant >= self.trigger_time + 10: # Rekam selama 10 detik
                    print(datetime.now().strftime("%b %d, %H:%M:%S"), "- Berhenti merekam")
                    self.isRecording = False
                else:
                    # Tambahkan tanggal ke frame
                    cv2.putText(curframe, datetime.now().strftime("%b %d, %H:%M:%S"), (25, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    self.writer.write(curframe) 
            
            if self.show:
                cv2.imshow("Image", curframe)
                cv2.imshow("Res", self.res)
                
            self.frame1gray = self.frame2gray.copy()
            
            c = cv2.waitKey(1) & 0xFF
            if c == 27 or c == 10: # Tekan 'Esc' untuk keluar
                break            
        
        # Bersihkan resource
        self.capture.release()
        if self.writer:
            self.writer.release()
        cv2.destroyAllWindows()
    
    def processImage(self, frame):
        self.frame2gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Cari perbedaan frame
        cv2.absdiff(self.frame1gray, self.frame2gray, self.res)
        
        # Hapus noise dan lakukan thresholding
        self.res = cv2.blur(self.res, (5, 5))
        kernel = np.ones((5, 5), np.uint8)
        self.res = cv2.morphologyEx(self.res, cv2.MORPH_OPEN, kernel)
        self.res = cv2.morphologyEx(self.res, cv2.MORPH_CLOSE, kernel)
        
        _, self.res = cv2.threshold(self.res, 10, 255, cv2.THRESH_BINARY_INV)

    def somethingHasMoved(self):
        min_threshold = (self.nb_pixels / 100.0) * self.threshold 
        nb = self.nb_pixels - cv2.countNonZero(self.res)
        return nb > min_threshold
        
if __name__ == "__main__":
    detect = MotionDetectorInstantaneous(doRecord=True)
    detect.run()