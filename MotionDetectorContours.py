import cv2
import numpy as np
from datetime import datetime
import time

class MotionDetectorAdaptative():
    
    def onChange(self, val): 
        self.threshold = val
    
    def __init__(self, threshold=5, doRecord=True, showWindows=True):
        self.writer = None
        self.doRecord = doRecord 
        self.show = showWindows 
    
        self.capture = cv2.VideoCapture(0)
        ret, self.frame = self.capture.read() 
        
        if not ret:
            raise Exception("Kamera tidak terdeteksi atau tidak dapat diakses.")
            
        self.height, self.width = self.frame.shape[:2]
        
        if doRecord:
            self.initRecorder()
        
        self.average_frame = np.float32(self.frame)
        self.absdiff_frame = None
        self.previous_frame = None
        
        self.surface = self.width * self.height
        self.currentsurface = 0
        self.currentcontours = []
        self.threshold = threshold
        self.isRecording = False
        self.trigger_time = 0 
        
        if showWindows:
            cv2.namedWindow("Image")
            # Set default threshold lebih rendah, misal 5% untuk adaptif
            cv2.createTrackbar("Detection threshold: ", "Image", self.threshold, 100, self.onChange)
        
    def initRecorder(self):
        codec = cv2.VideoWriter_fourcc(*'MJPG')
        filename = datetime.now().strftime("%b-%d_%H_%M_%S") + ".avi"
        self.writer = cv2.VideoWriter(filename, codec, 10.0, (self.width, self.height))

    def run(self):
        started = time.time()
        while True:
            ret, currentframe = self.capture.read()
            if not ret:
                break
                
            instant = time.time() 
            self.processImage(currentframe) 
            
            if not self.isRecording:
                if self.somethingHasMoved():
                    self.trigger_time = instant 
                    if instant > started + 10: 
                        print(datetime.now().strftime("%b %d, %H:%M:%S"), "- Sesuatu bergerak!")
                        if self.doRecord: 
                            self.isRecording = True
            
            # Gambar kontur secara terus-menerus
            if self.currentcontours:
                cv2.drawContours(currentframe, self.currentcontours, -1, (0, 0, 255), 2)

            if self.isRecording:
                if instant >= self.trigger_time + 10: 
                    print(datetime.now().strftime("%b %d, %H:%M:%S"), "- Berhenti merekam")
                    self.isRecording = False
                else:
                    cv2.putText(currentframe, datetime.now().strftime("%b %d, %H:%M:%S"), (25, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    self.writer.write(currentframe)
            
            if self.show:
                cv2.imshow("Image", currentframe)
                
            c = cv2.waitKey(1) & 0xFF
            if c == 27 or c == 10: # Esc
                break            
                
        self.capture.release()
        if self.writer:
            self.writer.release()
        cv2.destroyAllWindows()
    
    def processImage(self, curframe):
        # Gunakan Gaussian Blur untuk meminimalisasi false positive
        curframe_blur = cv2.GaussianBlur(curframe, (21, 21), 0)
        
        if self.absdiff_frame is None: 
            self.average_frame = np.float32(curframe_blur)
            self.absdiff_frame = np.zeros_like(curframe_blur)
            self.previous_frame = np.zeros_like(curframe_blur)
            self.gray_frame = np.zeros((self.height, self.width), np.uint8)
        else:
            # Hitung Running Average
            cv2.accumulateWeighted(curframe_blur, self.average_frame, 0.05)
        
        # Konversi kembali ke tipe data uint8
        self.previous_frame = cv2.convertScaleAbs(self.average_frame)
        
        cv2.absdiff(curframe_blur, self.previous_frame, self.absdiff_frame)
        
        # Konversi ke Grayscale untuk thresholding
        self.gray_frame = cv2.cvtColor(self.absdiff_frame, cv2.COLOR_BGR2GRAY)
        _, self.gray_frame = cv2.threshold(self.gray_frame, 50, 255, cv2.THRESH_BINARY)

        # Dilasi dan Erosi untuk mendapatkan gumpalan (blobs) objek
        kernel = np.ones((5, 5), np.uint8)
        self.gray_frame = cv2.dilate(self.gray_frame, kernel, iterations=2)
        self.gray_frame = cv2.erode(self.gray_frame, kernel, iterations=2)

    def somethingHasMoved(self):
        # Temukan kontur
        contours, _ = cv2.findContours(self.gray_frame.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        self.currentcontours = contours 
        
        # Hitung total area permukaan
        self.currentsurface = sum(cv2.contourArea(c) for c in contours)
        
        # Hitung rata-rata area kontur dibanding ukuran layar
        avg = (self.currentsurface * 100) / self.surface 
        
        return avg > self.threshold
        
if __name__ == "__main__":
    detect = MotionDetectorAdaptative(doRecord=True)
    detect.run()