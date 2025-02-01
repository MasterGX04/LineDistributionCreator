import tkinter as tk
from tkinter import ttk
import cv2
import time
from PIL import Image, ImageTk
import threading
from TrackItem import TrackItem

class VideoTrackItem(TrackItem):
    def __init__(self, canvas, videoPath, scale=100, scaleX=1.0, position=(0,0), baseHeight=720):
        super().__init__(scale, position, sourceImages={}, animations=[], type="video")
        self.canvas = canvas
        self.videoPath = videoPath
        self.cap = cv2.VideoCapture(videoPath)
        self.scale = scale
        self.scaleX = scaleX
        self.videoFrameId = None
        self.isPlaying = False
        self.isPaused = False
        self.thread = None
        self.baseHeight = baseHeight
        self.currentFrame = None
        
        # Get video dimensions
        if self.cap.isOpened():
            self.frameWidth = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frameHeight = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        else:
            raise FileNotFoundError(f"Video file not found: {videoPath}")
        
        self.adjustScale(baseHeight)
        self.setPosition()
        
    def adjustScale(self, currentHeight):
        """Adjust the video dimensions and scale based on the current height."""
        # Calculate the new scale as a percentage
        self.scale = (currentHeight / self.baseHeight) * 100
        
        self.newHeight = currentHeight
        self.newWidth = int(self.newHeight * (self.frameWidth / self.frameHeight))
        print(f"New height: {self.newHeight}, New width: {self.newWidth}")
        # self.canvas.config(width=self.newWidth, height=self.newHeight)
    
    def play(self):
        self.isPlaying = True
        self.isPaused = False
        if not self.thread or not self.thread.is_alive():  # Check if the thread is not already running
            self.thread = threading.Thread(target=self._playVideo, daemon=True)
            self.thread.start()
        else:
            self.isPaused = False
        
    def pause(self):
        self.isPaused = True
        
    def stop(self):
        self.isPlaying = False
        self.isPaused = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)  # Wait briefly for the thread to terminate
    
    def resize(self, currentHeight):
        """Resize video dimensions dynamically."""
        self.adjustScale(currentHeight)
        if self.videoFrameId:
            self.canvas.delete(self.videoFrameId)
            self.videoFrameId = None

    def _playVideo(self):
        # Get video frame rate (frames per second)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise ValueError("Invalid FPS detected in video file.")

        frameDuration = 1 / fps  # Duration of each frame in seconds
        lastFrameTime = time.time()
        
        while self.isPlaying and self.cap.isOpened():
            if self.isPaused:
                time.sleep(0.2)  # Wait briefly while paused
                lastFrameTime = time.time() 
                continue
            
            ret, frame = self.cap.read()
            if not ret:
                break
            frame = cv2.resize(frame, (self.newWidth, self.newHeight))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = ImageTk.PhotoImage(image=Image.fromarray(frame))
            
            if self.videoFrameId:
                self.canvas.itemconfig(self.videoFrameId, image=img)
            else:
                self.videoFrameId = self.canvas.create_image(self.position[0], self.position[1], image=img, anchor="nw")
                  # Keep a reference to avoid garbage collection
                # Push the video to the back layer
                self.canvas.tag_lower(self.videoFrameId)
            self.canvas.image = img
            self.canvas.coords(self.videoFrameId, self.position[0], self.position[1])
            self.canvas.update()

            # Control frame rate
            elapsedTime = time.time() - lastFrameTime
            sleepTime = max(0, frameDuration - elapsedTime)
            time.sleep(sleepTime)
            lastFrameTime = time.time()
        self.isPlaying = False

    def setPosition(self):
        x = 300 / 1920 * 1920 * self.scaleX - (self.newWidth / 2)
        self.position = (x, 0)
            
    def seek(self, timeMs):
        """Calculate the frame index based on the time in milliseconds"""
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if fps > 0:
            frameIndex = int((timeMs / 1000.0) * fps)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frameIndex)