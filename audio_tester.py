import tensorflow as tf
import os
import numpy as np
import time
import threading
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox
from pydub import AudioSegment
from pydub.utils import make_chunks
from TrackItem import TrackItem
from voice_training import extractFeatures
import pygame
from VideoTrack import VideoTrackItem
from navigation_arrows import NavigationArrows
import json
import codecs
from lyrics_box import LyricBox
from zoom_functions import ZoomManager, ProgressBarHandle, ProgressBarNavigator

# Load the trained model for a specific member
def loadModel(group, member):
    modelPath = f"./{group}/{member}/train/data/{member}_model.h5"
    if os.path.exists(modelPath):
        return tf.keras.models.load_model(modelPath)
    else:
        print(f"Model for {member} not found in {modelPath}.")
        return None
# End loadModel
    
# Load images for member
def loadMemberImages(groupName, members: dict):
    images = {}
    for memberObject in members:
        memberName = memberObject['name']
        darkImgPath = f"./group_icons/{groupName}/Dark {memberName}.png"
        lightImgPath = f"./group_icons/{groupName}/{memberName}.png"
        
        darkImg = Image.open(darkImgPath)
        lightImg = Image.open(lightImgPath)
        
        images[memberName] = {"dark": darkImg, "light": lightImg}
        
    return images
# end loadMemberImages

def detectVoiceInSegment(model, segmentFeatures):
    prediction = model.predict(np.expand_dims(segmentFeatures, axis=0))
    return prediction > 0.8

class VoiceDetectionApp:
    def __init__(self, root, trainingMember, members, model, images, testSongPath, vocalsOnlyPath, selectedGroup):
        self.root = root
        self.trainingMember = trainingMember
        self.members = members
        self.model = model
        self.images = images
        self.testSongPath = testSongPath
        self.playbackThread = None
        self.vocalsOnlyPath = vocalsOnlyPath
        self.selectedGroup = selectedGroup
        
        self.baseWidth = 1920
        self.baseHeight = 1080
        
        self.audio = AudioSegment.from_file(self.vocalsOnlyPath)
        self.chunk_duration = 40
        self.totalDurationMs = len(self.audio)
        self.chunks = [self.audio[i:i + self.chunk_duration] for i in range(0, len(self.audio), int(self.chunk_duration))]
        self.detectionResults = []
        self.currentChunkIndex = 0  # Track current playback position
        self.playbackOffset = 0
        self.previousX = 0
        self.isPlaying = False
        self.isPaused = False
        self.isProcessed = False
        self.isManualUpdate = False
        self.skipNextAutoUpdate = False
        # self.root.after(100, self.loadSavedLabels) 
        self.timeMarkers = {}
        self.lyrics = {}
        pygame.mixer.init()
            
        self.startPoints = []
        self.endPoints = []            
            
        self.startPointMarkers = {}
        self.endPointMarkers = {}
        
        self.canvas = tk.Canvas(root, width=1280, height=720, bg="white")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.onCanvasResize)
        
        self.memberImages = {}
        self.memberImageIds = {}
        self.progressBarWidth = int(1280 * 0.75)
        self.scaleX = 1.0
        self.scaleY = 1.0

        self.timeDisplayVar = tk.StringVar(value="00:00:000") # Display time iin MM:SS:milliseconds
        self.zoomManager = ZoomManager(self.canvas, self, None, self.totalDurationMs, self.chunk_duration, pygame)
        self.progressBarCanvas = tk.Canvas(self.canvas, width=self.progressBarWidth, height=20, bg="black")
        self.progressBarCanvas.place(relx=0.5, rely=0.9, anchor="center")
        self.navigationArrows = NavigationArrows(self.canvas, self, self.progressBarCanvas)
        # self.currentChunks = self.chunks[:self.zoomManager.currentChunksInView]
        
        self.currentSectionIndex = 0
        self.progressBarCanvas.place(relx=0.5, rely=0.9, anchor="center") # creates horizontal scale widget
        
        self.zoomManager.progressBar = self.progressBarCanvas
        
        self.timeDisplayLabel = tk.Label(self.canvas, textvariable=self.timeDisplayVar, bg="black", fg="white", font=("Arial", 12))
        self.timeDisplayLabel.place(relx=0.5, rely=0.85, anchor="center")
        
        self.progressBarCanvas.bind("<B1-Motion>", self.onDragHandle)    
        self.progressBarCanvas.bind("<ButtonPress-1>", self.onProgressBarPress)
        self.progressBarCanvas.bind("<ButtonRelease-1>", self.onProgressBarRelease)
        
        self.progressBarHandle = ProgressBarHandle(self.progressBarCanvas, self, self.progressBarWidth, self.chunk_duration)
        
        # Initialize VideoTrack
        videoPath = f"./training_data/{self.selectedGroup}/{os.path.basename(self.testSongPath).replace('.mp3', '.mp4')}"
        if os.path.exists(videoPath):
            self.videoTrackItem = VideoTrackItem(self.canvas, videoPath, scale=100, scaleX=self.scaleX, position=(0,0), baseHeight=720)
        
        self.labels = self.loadSavedLabels() # Store labels (member, start, end)
        self.root.after(50, self.initializeMemberImages)
        self.root.after(100, self.updateElementPositions)
        self.addControls(root)
        self.root.after(100, self.drawTimeMarkers)
        self.root.after(50, self.loadLyricsFromFile)
        
        self.lastKeyPressTime = 0
        self.updateTimer = 0
        self.enableRootKeybinds()
        self.canvas.focus_set() 
        self.selectedMarker = None
        self.root.after(50, self.addBackgroundImage)
        self.root.after(50, self.initializeArrows)
        self.uiHidden = False
        self.root.bind("<Control-h>", self.toggleUIElements)
    # end init
    
    def toggleUIElements(self, event=None):
        """Toggle visibility of navigation arrows, progress bar handle, progress bar canvas, and time markers."""
        self.uiHidden = not self.uiHidden  # Toggle visibility state
        newState = "hidden" if self.uiHidden else "normal"
        
        if hasattr(self.navigationArrows, "arrows"):
            for arrow in self.navigationArrows.arrows.values():
                self.canvas.itemconfig(arrow, state=newState)
        
        # Hide/Show Progress Bar Handle
        if hasattr(self.progressBarHandle, "handle"):
            self.canvas.itemconfig(self.progressBarHandle.handle, state=newState)
        
        if hasattr(self, "progressBarCanvas"):
            if self.uiHidden:
                self.progressBarCanvas.place_forget()  # Hides the canvas
            else:
                self.progressBarCanvas.place(relx=0.5, rely=0.9, anchor="center")  # Restores the canvas
        
        # Hide/Show Time Markers
        self.canvas.itemconfig("time_marker", state=newState)
        
        if hasattr(self, "timeDisplayLabel"):
            if self.uiHidden:
                self.timeDisplayLabel.place_forget()  # Hides the label
            else:
                self.timeDisplayLabel.place(relx=0.5, rely=0.85, anchor="center")
                
        self.zoomManager.toggleZoomUI()
    
    def addBackgroundImage(self):
        memberImage = next(iter(self.memberImages.values()))
        basePath = self.testSongPath.rsplit('\\', 1)[0]  # Remove everything after the last '\'
        whiteImagePath = os.path.join(basePath, "White.jpg")
        
        if memberImage:
            try:
                whiteImage = Image.open(whiteImagePath)
                whiteImageTk = ImageTk.PhotoImage(whiteImage)
                x = 750 / 1920 * self.baseWidth * self.scaleX
                y = 0
                
                self.lyricsBackgroundId = self.canvas.create_image(
                    x, y, anchor="nw", image=whiteImageTk
                ) 
                
                self.lyricsBackgroundId = whiteImageTk
                self.canvas.tag_raise(self.lyricsBackgroundId)
            except FileNotFoundError:
                print(f"Error: {whiteImagePath} not found.")
    
    def moveMarkerLeft(self, event):
        """
        Move the selected marker left by one chunkIndex.
        """
        self.moveMarker(-1)
        if (self.selectedLabel):
            self.updateLabelInJSON()

    def moveMarkerRight(self, event):
        """
        Move the selected marker right by one chunkIndex.
        """
        self.moveMarker(1)
        if (self.selectedLabel):
            self.updateLabelInJSON()
        
    def updateChunkText(self, newIndex):
        """Update the chunk index value displayed."""
        self.currentChunkIndex = newIndex
        self.chunkIndexLabel.config(text=str(self.currentChunkIndex))
        
    def initializeArrows(self):
        self.navigationArrows = NavigationArrows(self.canvas, self, self.progressBarCanvas)
        self.navigationArrows.updateArrows()
    
    def selectMarker(self, chunkIndex, markerType):
        self.selectedMarker = {"chunkIndex": chunkIndex, "type": markerType}
        print(f"Marker selected at {chunkIndex} with type {markerType}")
        if markerType == "start":
            self.canvas.itemconfig(self.startPointMarkers[chunkIndex], fill="turquoise")
        elif markerType == "end":
            self.canvas.itemconfig(self.endPointMarkers[chunkIndex], fill="pink")
        
        self.canvas.bind("<Delete>", self.deleteSelectedMarker)
        
    def deleteSelectedMarker(self, event=None):
        """
        Delete the selected marker and update all relevant data structures and JSON.
        """
        if not self.selectedMarker:
            return
        
        chunkIndex = self.selectedMarker["chunkIndex"]
        markerType = self.selectedMarker["type"]
        
        if markerType == "start":
            if chunkIndex in self.startPointMarkers:
                self.canvas.delete(self.startPointMarkers[chunkIndex])
                del self.startPointMarkers[chunkIndex]
                if chunkIndex in self.startPoints:
                    self.startPoints.remove(chunkIndex)  # Remove from startPoints
        elif markerType == "end":
            if chunkIndex in self.endPointMarkers:
                self.canvas.delete(self.endPointMarkers[chunkIndex])
                del self.endPointMarkers[chunkIndex]
                if chunkIndex in self.endPoints:
                    self.endPoints.remove(chunkIndex)  # Remove from endPoints
                
        self.removeLabelFromJSON(chunkIndex, markerType)
        self.selectedMarker = None
    
    def resetMarkerColor(self):
        """
        Reset the color of the previously selected marker, if any.
        """
        if not self.selectedMarker:
            return

        chunkIndex = self.selectedMarker["chunkIndex"]
        markerType = self.selectedMarker["type"]

        if markerType == "start" and chunkIndex in self.startPointMarkers:
            self.canvas.itemconfig(self.startPointMarkers[chunkIndex], fill="green")
        elif markerType == "end" and chunkIndex in self.endPointMarkers:
            self.canvas.itemconfig(self.endPointMarkers[chunkIndex], fill="red")
        self.selectedMarker = None
    
    def onMarkerClick(self, event):
        """
        Detect if a marker is clicked and darken its color.
        """
        self.resetMarkerColor()
        self.selectedMarker = None
        clickedItem = self.canvas.find_closest(event.x, event.y)
        
        for chunkIndex, marker in self.startPointMarkers.items():
            if marker == clickedItem[0]:
                if self.selectedMarker and self.selectedMarker["type"] == "start" and self.selectedMarker["chunkIndex"] != chunkIndex:
                    self.updateLabelInJSON()
                
                self.selectMarker(chunkIndex, "start")
                self.prepareLabelUpdate(chunkIndex, "start")
                return
        
        for chunkIndex, marker in self.endPointMarkers.items():
            if marker == clickedItem[0]:
                if self.selectedMarker and self.selectedMarker["type"] == "end" and self.selectedMarker["chunkIndex"] != chunkIndex:
                    self.updateLabelInJSON()
                    
                self.selectMarker(chunkIndex, "end")
                self.prepareLabelUpdate(chunkIndex, "end")
                return
            
        self.selectedMarker = None
        self.originalLabel = None
           
    def prepareLabelUpdate(self, chunkIndex, markerType):
        """
        Check if the selected marker belongs to a saved label and prepare for updates.
        """
        for label in self.labels:
            member, start, end = label
            if (markerType == "start" and start == chunkIndex) or (markerType == "end" and end == chunkIndex):
                self.selectedLabel = label
                self.originalLabel = label.copy()
                return
        self.selectedLabel = None
        self.originalLabel = None
    # end
    
    def updateLabelInJSON(self):
        """
        Save updated labels to JSON file
        """
        # print("Label update function called")
        if not self.selectedLabel:
            print("Label not selected")
            return
        
        fileNameWithoutExtension = os.path.splitext(os.path.basename(self.testSongPath))[0]
        labelFilePath = f"./saved_labels/{self.selectedGroup}/{fileNameWithoutExtension}_labels.json"
        
        try:
            # with open(labelFilePath, "r") as file:
            #     savedLabels = json.load(file)
            # for i, label in enumerate(savedLabels):
            #     if label[0] == self.originalLabel[0] and label[1] == self.originalLabel[1] and label[2] == self.originalLabel[2]:    
            #         savedLabels[i] = self.selectedLabel
            #         self.originalLabel = self.selectedLabel
            #         break
            sortedLabels = sorted(self.labels, key=lambda label: label[1])
            with open(labelFilePath, "w") as file:
                json.dump(sortedLabels , file, indent=4)
                
            # print(f"Labels saved to {labelFilePath}.")
            self.updateTimeMarkersDict()
            self.initializePositions()
        except Exception as e:
            print(f"Error saving labels to {labelFilePath}: {e}")
             
    def removeLabelFromJSON(self, chunkIndex, markerType):
        """
        Remove the label corresponding to the deleted marker and update the JSON file.
        """
        fileNameWithoutExtension = os.path.splitext(os.path.basename(self.testSongPath))[0]
        labelFilePath = f"./saved_labels/{self.selectedGroup}/{fileNameWithoutExtension}_labels.json" 
        
        try:
            self.labels = [
            label for label in self.labels
            if not ((markerType == "start" and label[1] == chunkIndex) or
                    (markerType == "end" and label[2] == chunkIndex))
            ]
            with open(labelFilePath, "w") as file:
                json.dump(self.labels, file, indent=4)       
        except Exception as e:
            print(f"Error updating labels in {labelFilePath}: {e}")
            
                            
    def moveMarker(self, direction):
        """
        Move the selected marker left (-1) or right (+1) by one chunkIndex.
        """
        def calculateX(chunkIndex):
            chunksInView = self.zoomManager.currentChunksInView
            return self.progressBarCanvas.winfo_x() + (chunkIndex % chunksInView / chunksInView) * self.progressBarWidth
        # end calculateX 
        
        if not self.selectedMarker:
            # print("No marker selected.")
            return
        
        chunkIndex = self.selectedMarker["chunkIndex"]
        markerType = self.selectedMarker["type"]
        
        newChunkIndex = chunkIndex + direction
        # print(f"Old chunk index: {chunkIndex}, New: {newChunkIndex}")
        if newChunkIndex < 0 or newChunkIndex >= len(self.chunks):
            print("Cannot move marker beyond bounds.")
            return
        
        y = self.progressBarCanvas.winfo_y()
        
        if markerType == "start":
            if chunkIndex in self.startPointMarkers:
                self.canvas.delete(self.startPointMarkers[chunkIndex])
                del self.startPointMarkers[chunkIndex]
                if chunkIndex in self.startPoints:
                    self.startPoints.remove(chunkIndex)
            else:
                print(f"Warning: Start marker at chunkIndex {chunkIndex} not found.")
        
            self.startPointMarkers[newChunkIndex] = self.canvas.create_line(
                calculateX(newChunkIndex), y - 20,
                calculateX(newChunkIndex), y,
                fill="green", width=4
            )
            self.startPoints.append(newChunkIndex)
        elif markerType == "end":
            if chunkIndex in self.endPointMarkers:
                self.canvas.delete(self.endPointMarkers[chunkIndex])
                del self.endPointMarkers[chunkIndex]
                if chunkIndex in self.endPoints:
                    self.endPoints.remove(chunkIndex)
            else:
                print(f"Warning: End marker at chunkIndex {chunkIndex} not found.")
            
            self.endPointMarkers[newChunkIndex] = self.canvas.create_line(
                calculateX(newChunkIndex), y - 20,
                calculateX(newChunkIndex), y,
                fill="red", width=4
            )
            self.endPoints.append(newChunkIndex)
            
        # Update label in self.labels if applicable
        if self.selectedLabel:
            # Update the label directly in self.labels if it's stored as a list
            for label in self.labels:
                if label == self.selectedLabel:
                    if markerType == "start":
                        label[1] = newChunkIndex  # Update the start index
                    elif markerType == "end":
                        label[2] = newChunkIndex  # Update the end index
                    self.selectedLabel = label  # Update the reference to the modified label
                    break
                
        self.selectedMarker["chunkIndex"] = newChunkIndex # This is run            
    
    def addControls(self, root):
        buttonFrame = tk.Frame(root, bg="gray")  # Light gray background for visibility
        buttonFrame.pack(fill="x", side="bottom")  # Place at the bottom
        
        self.singerVar = tk.StringVar(value=self.trainingMember)
        
        memberMapping = {member['name']: member for member in self.members}
        memberNames = memberMapping.keys()
        tk.OptionMenu(buttonFrame, self.singerVar, *memberNames).pack(side="left", padx=10, pady=10)
        
        # Add control buttons
        self.playButton = tk.Button(buttonFrame, text="Play", command=self.play, bg="white", fg="black")
        self.playButton.pack(side="left", padx=10, pady=10)
        
        self.pauseButton = tk.Button(buttonFrame, text="Pause", command=self.pause, bg="white", fg="black")
        self.pauseButton.pack(side="left", padx=10, pady=10)
        
        self.rewindButton = tk.Button(buttonFrame, text="Rewind", command=self.rewind, bg="white", fg="black")
        self.rewindButton.pack(side="left", padx=10, pady=10)
        
        self.forwardButton = tk.Button(buttonFrame, text="Forward", command=self.forward, bg="white", fg="black")
        self.forwardButton.pack(side="left", padx=10, pady=10)
        
        self.restartButton = tk.Button(buttonFrame, text="Restart", command=self.restart, bg="white", fg="black")
        self.restartButton.pack(side="left", padx=10, pady=10) 
        
        self.startPointButton = tk.Button(buttonFrame, text="Set Start Point", command=self.addStartPoint)
        self.startPointButton.pack(side="left", padx=10, pady=10)
        
        self.endPointButton = tk.Button(buttonFrame, text="Set End Point", command=self.addEndPoint)
        self.endPointButton.pack(side="left", padx=10, pady=10)
        
        self.addLabelsButton = tk.Button(buttonFrame, text="Add Labels", command=lambda: self.showAddLabelsMenu(event=None))
        self.addLabelsButton.pack(side="left", padx=10, pady=10)
        
        chunkIndexFrame = tk.Frame(buttonFrame, bg="gray")
        chunkIndexFrame.pack(side="right", padx=10, pady=10)  # Align to the right side

        tk.Label(chunkIndexFrame, text="Chunk Index:", bg="gray", fg="white", font=("Arial", 10)).pack(side="top")
        self.chunkIndexLabel = tk.Label(chunkIndexFrame, text=str(self.currentChunkIndex), bg="gray", fg="white", font=("Arial", 10))
        self.chunkIndexLabel.pack(side="top")
     
    def onCanvasResize(self, event):
        aspectRatio = self.baseWidth / self.baseHeight 
        self.progressBarWidth = int(self.canvas.winfo_width() * 0.75)
        
        if event.width / event.height > aspectRatio:
            # Width is too large, adjust based on height
            newHeight = event.height
            newWidth = int(newHeight * aspectRatio)
        else:
            # Height is too large, adjust based on width
            newWidth = event.width
            newHeight = int(newWidth / aspectRatio)
        
        self.scaleX = newWidth / self.baseWidth
        self.scaleY = newHeight / self.baseHeight
        
        self.progressBarCanvas.config(width=self.progressBarWidth)
        self.navigationArrows.updateArrows()
        self.updateElementPositions()
        
        self.drawTimeMarkers()
        
        if hasattr(self, "videoTrackItem"):
            # Adjust video height to fit canvas and maintain aspect ratio
            self.videoTrackItem.resize(newHeight)
    
    def updateElementPositions(self):
        """Update the position and size of all canvas elements based on the new scale."""
        for member, trackItem in self.memberImages.items():
            # Get current placement ratios
            scaledX, scaledY = trackItem.position
            
            newX = scaledX * self.scaleX * self.baseWidth
            newY = int(scaledY * self.scaleY * self.baseHeight)
            
            effectiveScale = trackItem.scale * self.scaleX 
            
            trackItem.resizeImages(effectiveScale)
             
            # Update the canvas image and position
            imageId = self.memberImageIds[member]
            imageKey = trackItem.currentImageKey
            trackItem.setImageId(imageId)
            self.canvas.itemconfig(imageId, image=trackItem.sourceImages[imageKey])
            self.canvas.coords(imageId, newX, newY)
        
        self.initializePositions()
        
    def initializePositions(self):
        for currentChunk in range(len(self.chunks)):
            for trackItem in self.memberImages.values():
                if currentChunk < len(self.chunks) - 4:
                    trackItem.checkAndSwap(currentChunk)
                    trackItem.updateAnimations(currentChunk)
                else:
                    trackItem.positionTimeline[currentChunk] = trackItem.positionTimeline[len(self.chunks) - 4]
        
    def initializeMemberImages(self):
        initialOffset = int(400 / 1080 * self.baseHeight * self.scaleY)
        yOffset = initialOffset
        initialScale = 40
        memberTimes = []

        for memberName, imgSet in self.images.items():
            darkImage = imgSet["dark"]
            lightImage = imgSet["light"]

            # Create ImageTk.PhotoImage instances from the resized images
            darkImgTk = ImageTk.PhotoImage(darkImage)
            
            scaledHeight = int(darkImgTk.height() * initialScale / 100)
            trackItem = TrackItem(  
                scale=initialScale,
                position=(0, yOffset),
                sourceImages={'dark': darkImage, 'light': lightImage},
                animations=[],
                parent=self,
                trackMember=memberName,
            )
            self.memberImages[memberName] = trackItem
            trackItem.resizeImages(initialScale)
            
            imageId = self.canvas.create_image(
                0, yOffset, image=trackItem.sourceImages["dark"], anchor="nw"
            )
            
            trackItem.setImageId(imageId)
            self.memberImageIds[memberName] = imageId
            yOffset += scaledHeight
            memberTimes.append(trackItem.timeline[len(self.chunks) - 1])
        
        for _, trackItem in self.memberImages.items():
            trackItem.setMaxTime(max(memberTimes))
        #print(f"Max time: {self.maxTime} Member times:", memberTimes) 
        
    #end initializeMemberImages 
     
    def updateTimeMarkersDict(self):
        self.timeMarkers = {}
        for chunkIndex in self.startPoints:
            sectionIndex = chunkIndex // self.zoomManager.currentChunksInView
            if sectionIndex not in self.timeMarkers:
                self.timeMarkers[sectionIndex] = []
            self.timeMarkers[sectionIndex].append(("start", chunkIndex))

        # Process endPointMarkers
        for chunkIndex in self.endPoints:
            sectionIndex = chunkIndex // self.zoomManager.currentChunksInView
            if sectionIndex not in self.timeMarkers:
                self.timeMarkers[sectionIndex] = []
            self.timeMarkers[sectionIndex].append(("end", chunkIndex))
        # Optionally redraw markers for the current section
        self.drawMarkers(self.progressBarHandle.currentSectionIndex)
     
    def loadSavedLabels(self):
        """Load saved labels from a JSON file and update markers"""
        songName = os.path.basename(self.testSongPath).replace(".mp3", "")
        labelFilePath = f"./saved_labels/{self.selectedGroup}/{songName}_labels.json"
        
        if not os.path.exists(labelFilePath):
            print(f"No saved labels fround at {labelFilePath}.") 
            return
        
        # Load json file
        try:
            with open(labelFilePath, "r") as file:
                savedLabels = json.load(file)
                
                for label in savedLabels:
                    member, start, end = label  # Parse the JSON format
                    if start not in self.startPoints:
                        self.startPoints.append(start)
                    if end not in self.endPoints:
                        self.endPoints.append(end)
                
                # Update startPoints, endPoints, and markers
                self.updateTimeMarkersDict()
                self.drawTimeMarkers()
                
                self.canvas.update()
                self.root.update_idletasks()
                return savedLabels
        except Exception as e:
            print(f"Error loading labels from {labelFilePath}: {e}")
            return None
            
    # end loadSavedLabels        
    
    def progressBarValueToTime(self, value):
        """Convert progress bar value to actual song time"""
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        return (self.currentSectionIndex * visibleDuration) + (value * self.chunk_duration)
    
    def timeToProgressBarValue(self, timeMs):
        """Convert actual song time to progress bar value."""
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        self.currentSectionIndex = timeMs // visibleDuration
        localTimeMs = timeMs % visibleDuration
        return localTimeMs // self.chunk_duration
    
    # Works properly
    def updateProgressBarHandle(self, timeMs): 
        """Update the progress bar handle position based on the current time."""
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        totalDuration = len(self.chunks) * self.chunk_duration
        
        timeInSection = timeMs - (self.currentSectionIndex * visibleDuration)
        
        progressRatio = timeInSection / visibleDuration
        x = (progressRatio * self.progressBarWidth) % self.progressBarWidth  # Calculate x position for the handle
        # Check for wrapping to the next section
        if self.previousX > self.progressBarWidth - 50 and x < 50:
            # print(f"Handle needs to wrap: Previous - {self.previousX}, X - {x}")
            self.currentSectionIndex += 1
            self.progressBarHandle.currentSectionIndex = self.currentSectionIndex
            if self.currentSectionIndex * visibleDuration >= totalDuration:
                self.currentSectionIndex = (totalDuration // visibleDuration) - 1  # Prevent overflow
                return
            
            #self.playbackOffset = self.currentSectionIndex * visibleDuration
            self.drawMarkers(self.currentSectionIndex)
            self.drawTimeMarkers()
        
        # Check for wrapping to the previous section
        elif self.previousX < 50 and x > self.progressBarWidth - 50:
            self.currentSectionIndex -= 1
            self.progressBarHandle.currentSectionIndex = self.currentSectionIndex
            if self.currentSectionIndex < 0:
                self.currentSectionIndex = 0  # Prevent underflow
                return
            
            #self.playbackOffset = self.currentSectionIndex * visibleDuration
            self.drawTimeMarkers()
            self.drawMarkers(self.currentSectionIndex)
            x = self.progressBarWidth  # Reset x position for the previous section
        
        # Move the progress bar handle to the new position  
        self.progressBarHandle.move(x, self.currentSectionIndex)

        # Update the previous x position
        self.previousX = x
            
    # Works properly
    def updateVisibleRange(self, value):
        """Handle progress bar changes while zoomed in with bar"""
        value = int(value)
        totalChunks = len(self.chunks)
        visibleChunks = self.zoomManager.currentChunksInView
        
        startChunk = int((value / 800) * totalChunks)
        startChunk = min(max(0, startChunk), totalChunks - visibleChunks)
        
        self.currentSectionIndex = startChunk
        self.updateProgressBar()
        self.updateCurrentTime(value)
    
    # Works properly
    def onDragHandle(self, event):
        """Handle dragging progress bar handle"""
        # Constrict x to bounds of progress bar
        x = max(0, min(event.x, self.progressBarWidth))
        self.progressBarHandle.jump(x, self.currentSectionIndex)
        
        pygame.mixer.music.pause()
        if hasattr(self, "videoTrackItem"):
            self.videoTrackItem.pause()
        
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        
        progressRatio = x / self.progressBarWidth
        #print(f"Current progressRatio: {progressRatio }")
        newTimeMs = int(visibleDuration * (self.currentSectionIndex + progressRatio))
        self.currentChunkIndex = int(newTimeMs / self.chunk_duration)
        self.updateChunkText(self.currentChunkIndex)
        self.updateProgressBarHandle(newTimeMs)
        self.updateDisplayedTime(newTimeMs)
        
        if hasattr(self, "videoTrackItem"):
            self.videoTrackItem.seek(newTimeMs)
        
        self.isManualUpdate = True
        
    def updateProgressBar(self):
        """Redraw progress bar based on visible range"""
        totalChunks = len(self.chunks)
        visibleChunks = self.zoomManager.currentChunksInView
        
        # Ensure current section index remains within bounds
        # self.currentChunkIndex = min(self.currentSectionIndex * visibleChunks, totalChunks - visibleChunks)
        # self.currentChunks = self.chunks[self.currentChunkIndex: self.currentChunkIndex + visibleChunks]
        
        playbackTime = self.playbackOffset + pygame.mixer.music.get_pos()
        self.updateTimeMarkersDict()
        self.updateProgressBarHandle(playbackTime)
                    
    def drawTimeMarkers(self):
        """Draw time markers for current section"""
        if hasattr(self, "uiHidden") and self.uiHidden:
            return  # Skip drawing if UI is hidden
        
        self.canvas.delete("time_marker")
        
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        
        # Determines start of current section
        startTimeMs = self.progressBarHandle.currentSectionIndex * visibleDuration
        # print(f"Start time in {self.currentSectionIndex}: {startTimeMs / 1000} secs")
        
        progressBarX = self.progressBarCanvas.winfo_x()
        progressBarY = self.progressBarCanvas.winfo_y()
        progressBarWidth = self.progressBarWidth  # Use the updated width
        markerIntervalMs = visibleDuration // 10  # Interval in milliseconds

        for i in range(11):
            # Calculate x position and time
            x = progressBarX + (i / 10) * progressBarWidth
            timeMs = startTimeMs + (i * markerIntervalMs)
            minutes = timeMs // 60000
            seconds = (timeMs % 60000) // 1000
            milliseconds = round((timeMs % 1000) / 10)

            if milliseconds == 100:  # Handle overflow
                seconds += 1
                milliseconds -= 100
            if seconds == 60:  # Handle minute overflow
                minutes += 1
                seconds = 0

            # Draw the time marker line
            self.canvas.create_line(
                x, progressBarY - 20,
                x, progressBarY,
                fill="gray",
                tags="time_marker"
            )
            # Draw the timestamp
            timestamp = f"{seconds:02}:{milliseconds:02}" if minutes == 0 else f"{minutes:01}:{seconds:02}:{milliseconds:02}"
            self.canvas.create_text(
                x,
                progressBarY - 30,
                text=timestamp,
                fill="blue",
                font=("Arial", 8),
                tags="time_marker"
            )
            
    def getMemberColor(self, name):
        for member in self.members:
            if member['name'] == name:
                return member['color']
        return None
    # end getMemberColor
        
    def showAddLabelsMenu(self, event):
        # Create menu window
        labelMenu = tk.Toplevel(self.root)
        labelMenu.title("Add labels")
        labelMenu.geometry("400x400")
        labelMenu.transient(self.root)  # Make it a child of the root window
        labelMenu.grab_set()
        
        # Frame for checklist
        checklistFrame = tk.Frame(labelMenu)
        checklistFrame.pack(pady=0, fill="both", expand=True)
        
        canvas = tk.Canvas(checklistFrame)
        scrollFrame = tk.Frame(canvas)
        scrollbar = tk.Scrollbar(checklistFrame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=scrollFrame, anchor="nw")
        
        # Update scroll region
        def updateScrollRegion(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollFrame.bind("<Configure>", updateScrollRegion)
        
        def onMouseWheel(event):
            """Allow scrolling only inside this window (avoid conflicts)."""
            if labelMenu.winfo_exists():
                canvas.yview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", onMouseWheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        
        checkboxes = {}
        for i, (member, startPoint, endPoint) in enumerate(self.getLabels()):
            var = tk.BooleanVar()
            
            memberText = f" -> {member}" if member is not None else ""
            text = f"Start: {startPoint}, End: {endPoint}{memberText}"
            
            color = self.getMemberColor(member) if member else "black"
            checkbox = tk.Checkbutton(
                scrollFrame,
                text=text,
                variable=var,
                anchor="w",
                bg="lightgray",
                fg=color,
                selectcolor="darkgrey"
            )
            checkbox.grid(row=i, column=0, stick="w", padx=5, pady=2)
            checkboxes[(startPoint, endPoint)] = var
            
            # If a member is assigned, add button to creeate lyrics with preset startChunk
            if member:
                #print("Assigned member:", member)
                def createAddLyricsCallback(startPoint=startPoint, memberName=''):
                    return lambda: self.addLyricBox(startChunk=startPoint - 9, memberName=memberName)
                
                addLyricButton = tk.Button(
                    scrollFrame,
                    text="Add Lyrics",
                    command=createAddLyricsCallback(startPoint, member),
                    bg="lightblue")
                addLyricButton.grid(row=i, column =1, padx=5, pady=2)
        
        memberLabel = tk.Label(labelMenu, text="Choose Member:")
        memberLabel.pack(pady=5)
        memberMapping = {member['name']: member for member in self.members}
        memberNames = list(memberMapping.keys())
        memberVar = tk.StringVar(value=memberNames[0] if memberNames else "")
        memberDropdown = ttk.Combobox(labelMenu, textvariable=memberVar, values=memberNames, state="readonly")
        memberDropdown.pack(pady=5)
        
        def saveSelectedLabels():
            selectedLabels = []
            for (startPoint, endPoint), var in checkboxes.items():
                if var.get(): # Checks if checkbox is checked
                    member = memberVar.get()
                    if member:
                        label = [member, startPoint, endPoint]
                        self.labels.append(label)
                        selectedLabels.append(label)
                        print(f"Label saved: {label}")
                        
                        trackItem = self.memberImages[member]
                        if trackItem:
                            trackItem.initializeTimeline()
                if selectedLabels:
                    self.saveLabels(self.selectedGroup, self.testSongPath)
                labelMenu.destroy()
        
        buttonFrame = tk.Frame(labelMenu)
        buttonFrame.pack(pady=10)
        
        saveButton = tk.Button(buttonFrame, text="Save Labels", command=saveSelectedLabels)
        saveButton.pack(side="left", padx=5)
        
        closeButton = tk.Button(buttonFrame, text="Close", command=labelMenu.destroy)
        closeButton.pack(side="left", padx=5)
    
    def addLyricBox(self, event=None, startChunk=None, memberName=None):
        """Opens a new window to input lyric details and add it to the canvas."""
        inputWindow = tk.Toplevel(self.root)
        inputWindow.title("Add Lyrics Box")
        inputWindow.geometry("600x400")
        inputWindow.transient(self.root)  # Make it a child of the root window
        inputWindow.grab_set()
        
        self.disableRootKeybinds()
        
        # Make the window scrollable
        canvas = tk.Canvas(inputWindow)
        scrollFrame = tk.Frame(canvas)
        scrollbar = tk.Scrollbar(inputWindow, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=scrollFrame, anchor="nw")

        def updateScrollRegion(event):
            """Update the scroll region when widgets are added."""
            canvas.configure(scrollregion=canvas.bbox("all"))

        def onMouseWheel(event):
            """Enable scrolling on Windows and MacOS."""
            if inputWindow.winfo_exists():
                canvas.yview_scroll(-1 * (event.delta // 120), "units")  # Windows
        
        scrollFrame.bind("<Configure>", updateScrollRegion)
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", onMouseWheel))  # Activate scrolling
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
                
        memberMapping = {member['name']: member for member in self.members}
        memberNames = list(memberMapping.keys())
        tk.Label(scrollFrame, text="Member Name:").pack(pady=5)
        
        membersFrame = tk.Frame(scrollFrame)
        membersFrame.pack(pady=5)
        
        memberVars = []
        memberFrames = []
        
        def addMemberDropdown(defaultName=None):
            """Add a new member dropdown to the input window."""
            if len(memberVars) > 3:
                return
            
            frame = tk.Frame(membersFrame)
            frame.pack(pady=2)
            
            var= tk.StringVar(value=defaultName if defaultName else memberNames[0])
            dropdown = tk.OptionMenu(frame, var, *memberNames)
            dropdown.pack(side="left")
            
            def removeMember():
                frame.destroy()
                memberVars.remove(var)
                memberFrames.remove(frame)
                    
            removeButton = tk.Button(frame, text="X", command=removeMember)
            removeButton.pack(side="left", padx=5)
            
            memberVars.append(var)
            memberFrames.append(frame)
        
        addMemberDropdown(memberName)
        
        addButton = tk.Button(scrollFrame, text="Add Member", command=addMemberDropdown)
        addButton.pack(pady=5)
        
        langVar = tk.StringVar(value="Korean")
        
        def switchLanguage():
            """Toggle visibility of Korean/Romanization fields based on language selection."""
            if langVar.get() == "English":
                koreanFrame.pack_forget()
                romanFrame.pack_forget()
            else:
                koreanFrame.pack(fill="x", pady=5)
                romanFrame.pack(fill="x", pady=5)    
            
        langFrame = tk.Frame(scrollFrame)
        langFrame.pack(fill="x", pady=5)
        tk.Radiobutton(langFrame, text="Korean", variable=langVar, value="Korean", command=switchLanguage).pack(side="left", padx=10)
        tk.Radiobutton(langFrame, text="English", variable=langVar, value="English", command=switchLanguage).pack(side="left")
        
        # Dropdown for duplicating lyrics
        tk.Label(scrollFrame, text="Duplicate Existing Lyrics:").pack(pady=5)
        duplicateVar = tk.StringVar(value="None")
        lyricOptions = ["None"] + [f"{lyric.memberName} -> {lyric.startChunk}" for lyric in self.lyrics.values()]  
        duplicateDropdown = tk.OptionMenu(scrollFrame, duplicateVar, *lyricOptions)
        duplicateDropdown.pack(padx=5)
        
        # Korean Lyric Field
        koreanFrame = tk.Frame(scrollFrame)
        koreanFrame.pack(fill="x", pady=5)
        tk.Label(koreanFrame, text="Korean Lyric:").pack(anchor="w")
        koreanEntry = tk.Text(koreanFrame, height=4, wrap="word")
        koreanEntry.pack(fill="x", padx=10)

        # Romanization Field
        romanFrame = tk.Frame(scrollFrame)
        romanFrame.pack(fill="x", pady=5)
        tk.Label(romanFrame, text="Romanization:").pack(anchor="w")
        romanEntry = tk.Text(romanFrame, height=4, wrap="word")
        romanEntry.pack(fill="x", padx=10)

        # English Translation Field
        engFrame = tk.Frame(scrollFrame)
        engFrame.pack(fill="x", pady=5)
        tk.Label(engFrame, text="English Translation:").pack(anchor="w")
        engEntry = tk.Text(engFrame, height=4, wrap="word")
        engEntry.pack(fill="x", padx=10)

        # Starting Chunk Field
        chunkFrame = tk.Frame(scrollFrame)
        chunkFrame.pack(fill="x", pady=5)
        tk.Label(chunkFrame, text="Starting Chunk:").pack(anchor="w")
        chunkEntry = tk.Entry(chunkFrame)
        if startChunk is not None:
            chunkEntry.insert(0, str(startChunk))
        chunkEntry.pack(fill="x", padx=10)
            
        def fillFromDuplicate(*args):
            selectedText = duplicateVar.get()
            if selectedText == "None":
                return 
            selectedChunk = int(selectedText.split(" -> ")[1])
            selectedLyric = self.lyrics[selectedChunk]
            
            langVar.set(selectedLyric.language)
            switchLanguage()
            
            koreanEntry.delete("1.0", "end")
            koreanEntry.insert("1.0", selectedLyric.koreanLyric)

            romanEntry.delete("1.0", "end")
            romanEntry.insert("1.0", selectedLyric.romanization)

            engEntry.delete("1.0", "end")
            engEntry.insert("1.0", selectedLyric.englishTrans)
            
        duplicateVar.trace("w", fillFromDuplicate)
            
        def submit():
            members = [var.get() for var in memberVars]
            
            if len(members) != len(set(members)):
                messagebox.showwarning("Duplicate Members", "Each member must be unique. Please select different members.")
                return 
            
            koreanLyric = koreanEntry.get("1.0", "end").strip() if langVar.get() == "Korean" else ""
            romanization = romanEntry.get("1.0", "end").strip() if langVar.get() == "Korean" else ""
            englishTrans = engEntry.get("1.0", "end").strip()
            startChunkValue = int(chunkEntry.get())
            
            membersData = members if len(members) > 1 else members[0]
            
            lyricBox = LyricBox(self.canvas, self, membersData, koreanLyric, romanization, englishTrans, startChunkValue, langVar.get())
            self.lyrics[startChunk] = lyricBox
            
            self.lyricPositions = {}
            self.initializeAllLyricPositions(self.lyrics)
            
            fileNameWithoutExtension = os.path.splitext(os.path.basename(self.testSongPath))[0]
            lyricsPath = f"./saved_labels/{self.selectedGroup}/{fileNameWithoutExtension}_lyrics.json"
            
            os.makedirs(os.path.dirname(lyricsPath), exist_ok=True)
            
            existingLyrics = []
            if os.path.exists(lyricsPath):
                with codecs.open(lyricsPath, "r", encoding="utf-8", errors="ignore") as file:
                    try:
                        existingLyrics = json.load(file)
                    except json.JSONDecodeError:
                        existingLyrics = []    
            
            newLyricEntry = {
                "language": langVar.get(),
                "memberName": members,
                "korean": koreanLyric,
                "romanization": romanization,
                "english": englishTrans,
                "startChunk": startChunkValue
            }
            
            existingLyrics.append(newLyricEntry)
            # Sort by startChunk
            sortedLyrics = sorted(existingLyrics, key=lambda x: x["startChunk"])
            
            # Save back to JSON file
            with codecs.open(lyricsPath, "w", encoding="utf-8") as file:
                json.dump(sortedLyrics, file, ensure_ascii=False, indent=4)
            
            self.enableRootKeybinds()
            inputWindow.destroy()
        
        submitFrame = tk.Frame(inputWindow)
        submitFrame.pack(side="bottom")
        submitButton = tk.Button(submitFrame, text="Submit", command=submit)
        submitButton.pack(pady=10, fill="x")
        
        inputWindow.protocol("WM_DELETE_WINDOW", lambda: (self.enableRootKeybinds(), inputWindow.destroy()))
        self.root.wait_window(inputWindow)
    
    def disableRootKeybinds(self):
        """Temporarily unbind all root-level keybindings while user is typing."""
        self.root.unbind("<Left>")
        self.root.unbind("<Right>")
        self.canvas.unbind("<Button-1>")
        self.canvas.unbind("<KeyPress-a>")
        self.canvas.unbind("<KeyPress-d>")
        self.canvas.unbind("<KeyPress-s>")
        self.canvas.unbind("<KeyPress-q>")
        self.canvas.unbind("<KeyPress-w>")
        self.canvas.unbind("<KeyPress-l>")
        self.canvas.unbind_all("<space>")

    def enableRootKeybinds(self):
        """Rebind all root-level keybindings after the lyric window is closed."""
        self.root.bind("<Left>", self.moveBackwardByChunks)
        self.root.bind("<Right>", self.moveForwardByChunks) 
        self.canvas.bind("<Button-1>", self.onMarkerClick)
        self.canvas.bind("<KeyPress-a>", self.moveMarkerLeft)
        self.canvas.bind("<KeyPress-d>", self.moveMarkerRight)
        self.canvas.bind("<KeyPress-s>", self.showAddLabelsMenu)
        self.canvas.bind("<KeyPress-q>", self.addStartPoint)
        self.canvas.bind("<KeyPress-w>", self.addEndPoint)
        self.canvas.bind("<KeyPress-l>", self.addLyricBox)
        self.canvas.bind_all("<space>", self.togglePlayPause)
        
    def loadLyricsFromFile(self):
        """Loads lyrics from a JSON file and adds them to self.lyrics."""
        fileNameWithoutExtension = os.path.splitext(os.path.basename(self.testSongPath))[0]
        lyricsFilePath = f"./saved_labels/{self.selectedGroup}/{fileNameWithoutExtension}_lyrics.json"
        
        if not os.path.exists(lyricsFilePath):
            print(f"Lyrics file not found: {lyricsFilePath}")
        
        try:
            with codecs.open(lyricsFilePath, "r", encoding="utf-8", errors="ignore") as file:
                lyricsData = json.load(file)
        except json.JSONDecodeError:
            print(f"Error loading JSON file: {lyricsFilePath}")
            return
        

        for lyric in lyricsData:
            language = lyric["language"]
            startChunk = lyric["startChunk"]
            memberName = lyric["memberName"]
            koreanLyric = lyric.get("korean", "")
            romanization = lyric.get("romanization", "")
            englishTrans = lyric.get("english", "")
            
            lyricBox = LyricBox(self.canvas, self, memberName, koreanLyric, romanization, englishTrans, startChunk, language)
            
            self.lyrics[startChunk] = lyricBox
            
        self.initializeAllLyricPositions(self.lyrics)
    
    def initializeAllLyricPositions(self, lyrics):
        """Precompute the positions for all lyric boxes before playback starts."""
        if not hasattr(self, "lyricPositions"):
            self.lyricPositions = {}  # Ensure lyricPositions exists
        
        for startChunk, lyricBox in lyrics.items():
            lyricBox.initializeLyricPosition()
        
        # print('Lyric positions:', self.lyricPositions)
        
    def renderLyrics(self, chunkIndex):
        """Render lyrics based on the most recent chunkIndex if the exact one is missing."""
        if chunkIndex not in self.lyricPositions:
            availableChunks = sorted(self.lyricPositions.keys())
            recentChunk = max((c for c in availableChunks if c <= chunkIndex), default=None)
            if recentChunk is None:
                return  # No previous lyrics to display
            chunkIndex = recentChunk  # Use the most recent chunkIndex
        
        currentLyrics = self.lyricPositions.get(chunkIndex, [])
        if currentLyrics:
            visibleStartChunks = set(startChunk for startChunk, _ in currentLyrics)

            # Hide lyrics that are no longer visible
            for startChunk in list(self.lyrics.keys()):
                if startChunk not in visibleStartChunks:
                    self.lyrics[startChunk].hide()

            previousPositions = {startChunk: yPos for startChunk, yPos in self.lyricPositions.get(chunkIndex - 1, [])}
            
            # Show and reposition the correct lyrics
            for startChunk, yPos in currentLyrics:
                if startChunk in self.lyrics:
                    lyricBox = self.lyrics[startChunk]
                    lyricBox.show()
                    if previousPositions.get(startChunk) != yPos:
                        lyricBox.setPosition(yPos)

            
    def updateCanvasForCurrentPosition(self, chunkIndex):
        """Highlight the corresponding member's image if their voice matches the current time."""
        membersCurrentlySinging = set()
       
        for member, start, end in self.labels:
            if start <= chunkIndex <= end:
                membersCurrentlySinging.add(member)
        
        # Update canvas for each member
        for member, trackItem in self.memberImages.items():
            imageId = self.memberImageIds[member]
            trackItem.updateAndDrawTimer(chunkIndex)
            if chunkIndex > trackItem.lastUpdateChunk:
                trackItem.switchImage("clear")
            elif member in membersCurrentlySinging:
                trackItem.switchImage("light")
            else:
                trackItem.switchImage("dark")
                
            self.canvas.itemconfig(imageId, image=trackItem.sourceImages[trackItem.currentImageKey]) 
        
        self.renderLyrics(chunkIndex)
                
        self.canvas.update()
    # end
    
    def onProgressBarPress(self, event):
        """Set manual update flag when user starts interacting with the progress bar."""
        self.isManualUpdate = True
    
    # Fix conflict with onDragHandle
    def onProgressBarRelease(self, event):
        """Unset manual update flag when user stops interacting with the progress bar."""
        x = max(0, min(event.x, self.progressBarWidth))  # Constrain x within the canvas bounds
        self.progressBarHandle.jump(x, self.currentSectionIndex)
        # Calculate the new start chunk based on the handle's x position
        visibleDuration = self.zoomManager.currentChunksInView * self.chunk_duration
        progressRatio = x / self.progressBarWidth
        newTimeMs = int(visibleDuration * (self.currentSectionIndex + progressRatio))
        
        # Updates the chunk index
        self.currentChunkIndex = int(newTimeMs / self.chunk_duration)
        self.updateChunkText(self.currentChunkIndex)
        # print(f"Released at {newTimeMs}")
        
        self.updateCurrentTime(newTimeMs)
        # self.updateProgressBarHandle(newTimeMs)
        # Restart playback at the new position => This is normal
        pygame.mixer.music.set_pos(newTimeMs / 1000)
        if hasattr(self, "videoTrackItem"):
            self.videoTrackItem.seek(newTimeMs)
            
        if not self.isPaused:
            pygame.mixer.music.unpause()
            if hasattr(self, "videoTrackItem"):
                self.videoTrackItem.play()
            self.playWithSavedResults(newTimeMs) # Annoying issue
        # Sync music playback with the new chunk index
        
    def moveBackwardByChunks(self, event):
        """Move backward by five frames."""
        currentTime = int(time.time() * 1000)
        if currentTime - self.lastKeyPressTime < 250: return
        
        self.lastKeyPressTime = currentTime
        
        newPlaybackTime = max(0, self.playbackOffset - 5000)
        
        self.currentChunkIndex = int(newPlaybackTime / self.chunk_duration)
        self.playbackOffset = newPlaybackTime
        print(f"Moved backward to chunk index: {self.currentChunkIndex}, Playback time: {newPlaybackTime}ms")
        self.updateProgressBarHandle(newPlaybackTime)
        self.updateProgressBar(newPlaybackTime)
        self.updateCanvasForCurrentPosition()
        
        if self.isPaused:
            return
        
        # Update playback position
        pygame.mixer.music.stop()
        pygame.mixer.music.play(start=newPlaybackTime / 1000)

    def moveForwardByChunks(self, event):
        """Move forward by five chunks."""
        currentTime = int(time.time() * 1000)
        if currentTime - self.lastKeyPressTime < 250: return
        
        self.lastKeyPressTime = currentTime
        
        newPlaybackTime = min(self.totalDurationMs, self.playbackOffset + 5000)
        
        # Calculate the playback time
        self.currentChunkIndex = int(newPlaybackTime / self.chunk_duration)
        self.playbackOffset = newPlaybackTime
        print(f"Moved forward to chunk index: {self.currentChunkIndex}, Playback time: {newPlaybackTime}ms")

        # Update UI
        self.updateProgressBar(newPlaybackTime)
        self.updateProgressBarHandle(newPlaybackTime)
        self.updateCanvasForCurrentPosition()
        
        if self.isPaused: return
        
        # Update playback position
        pygame.mixer.music.stop()
        pygame.mixer.music.play(start=newPlaybackTime / 1000)
    
    def getLabels(self):
        matchedPoints = []
        unmatchedStartPoints = []
        
        sortedStartPoints = sorted(self.startPoints)
        sortedEndPoints = sorted(self.endPoints)
        
        usedEndIndices = set()
        
        for startPoint in sortedStartPoints:
            closestEndIndex = None
            for i, endPoint in enumerate(sortedEndPoints):
                if i in usedEndIndices:
                    continue
                if endPoint > startPoint:
                    closestEndIndex = i
                    break
            
            if closestEndIndex is not None:
                endPoint = sortedEndPoints[closestEndIndex]
                
                matchedLabel = None
                for label in self.labels:
                    member, labelStart, labelEnd = label
                    if labelStart == startPoint and labelEnd == endPoint:
                        matchedLabel = member
                        break
                
                if matchedLabel:
                    matchedPoints.append((matchedLabel, startPoint, endPoint))
                else:
                    matchedPoints.append((None, startPoint, endPoint)) 

                usedEndIndices.add(closestEndIndex)
            else:
                unmatchedStartPoints.append(startPoint)

        # print("Matched points:", matchedPoints)
        return matchedPoints

    # Helper function to check if chunk is in any area
    def isInStartOrEnd(self):
        if self.currentChunkIndex in self.startPoints or self.currentChunkIndex in self.endPoints:
            return True
        
        return False
    # End isInStartOrEnd
    
    def togglePlayPause(self, event):
        if self.isPlaying and not self.isPaused:
            self.pause()
        elif self.isPaused:
            self.play()
    
    def updateDisplayedTime(self, timeMs):
        """Update time display based on milliseconds"""
        minutes = timeMs // 60000
        if minutes > 3:
            print(f"Display time error with timeMs {timeMs}")
        seconds = (timeMs % 60000) // 1000
        milliseconds = timeMs % 1000
        self.timeDisplayVar.set(f"{minutes:02}:{seconds:02}.{milliseconds:03}")
        
    def addStartPoint(self, event=None):
        if self.isInStartOrEnd:    
            self.startPoints.append(self.currentChunkIndex)
            self.addMarkerToSection(self.currentChunkIndex, "start")
            print(f"Start point set at chunk {self.currentChunkIndex}.")
            
        else:
            print(f"Chunk {self.currentChunkIndex} already marked as a start or end point.")

    def addEndPoint(self, event=None):
        if self.isInStartOrEnd:
            self.endPoints.append(self.currentChunkIndex)
            self.addMarkerToSection(self.currentChunkIndex, "end")
            print(f"End point set at chunk {self.currentChunkIndex}.")
        
        else:
            print(f"Chunk {self.currentChunkIndex} already marked as a start or end point.")
        
    def clearAllMarkers(self):
        """
        Clear all start and end markers from the canvas and reset marker dictionaries.
        """
        # Remove all start markers
        for marker in self.startPointMarkers.values():
            self.canvas.delete(marker)
        self.startPointMarkers.clear()

        # Remove all end markers
        for marker in self.endPointMarkers.values():
            self.canvas.delete(marker)
        self.endPointMarkers.clear()
        
    def drawMarkers(self, sectionIndex):
        self.clearAllMarkers()
        
        if sectionIndex not in self.timeMarkers:
            # print(f"No markers to draw for sectionIndex {sectionIndex}.")
            return
        
        chunksInView = self.zoomManager.currentChunksInView
        # print(f"Current chunks in view: {chunksInView}")
        
        for markerType, chunkIndex in self.timeMarkers[sectionIndex]:
            relativeX = self.progressBarCanvas.winfo_x() + (chunkIndex % chunksInView / chunksInView) * self.progressBarWidth

            x = self.canvas.canvasx(relativeX)
            y = self.progressBarCanvas.winfo_y()
        
            if x < 0 or x > self.canvas.winfo_width():
                print(f"Marker at chunk {chunkIndex} is out of bounds (x={x}).")
                return
        
            if markerType == "start":
                if chunkIndex not in self.startPointMarkers:
                    marker = self.canvas.create_line(
                        x, y - 20, 
                        x, y, 
                        fill="green", width=4
                    )
                    self.startPointMarkers[chunkIndex] = marker
            elif markerType == "end":
                if chunkIndex not in self.endPointMarkers:
                    marker = self.canvas.create_line(x, y - 20, x, y, fill="red", width=4)
                    self.endPointMarkers[chunkIndex] = marker
    # end drawMarkers
        
    def updatePlaybackPosition(self):
        """Periodically update progress bar handle during playback"""
        if self.isPlaying and not self.isPaused:
            # Get the current playback position in milliseconds
            playbackTime = self.playbackOffset + pygame.mixer.music.get_pos()

            # Update the handle position
            self.updateProgressBarHandle(playbackTime)

            # Update displayed time
            self.updateDisplayedTime(playbackTime)

            # Schedule the next update
            self.root.after(50, self.chunk_duration)
            
    def updateCurrentTime(self, newTimeMs):
        """Update the current time based on the progress bar value."""
        if not self.isManualUpdate: return
        
        self.playbackOffset = newTimeMs
        # self.currentChunkIndex = int(newTimeMs / self.chunk_duration)
        # print(f"Manual update to chunk index: {self.currentChunkIndex}, Time: {newTimeMs} ms")
        
        # if not self.isPaused:
        #     pygame.mixer.music.stop()
        #     pygame.mixer.music.play(start=newTimeMs / 1000)
        #     self.updatePlaybackPosition()
        
        self.skipNextAutoUpdate = True
        self.updateDisplayedTime(newTimeMs)
        self.updateProgressBarHandle(newTimeMs)
        self.updateCanvasForCurrentPosition(int(newTimeMs / self.chunk_duration))
    # end updateCurrentTime
            
    def play(self):
        # Play from saved detection results
        if self.playbackOffset < 0:
            self.playbackOffset = 0
        
        if self.isPlaying:
            if self.isPaused:
                pygame.mixer.music.unpause()
                # print(f"Play Playback time: {playbackTime}\n Current chunk: {self.currentChunkIndex}")
                self.isPaused = False
                
                if hasattr(self, "videoTrackItem"):
                    currentAudioTimeMs = pygame.mixer.music.get_pos() + self.playbackOffset
                    self.videoTrackItem.seek(self.currentChunkIndex * self.chunk_duration)
                    self.videoTrackItem.play()
                self.playWithSavedResults(self.currentChunkIndex * self.chunk_duration)
            return
        else:  
            if hasattr(self, "videoTrackItem"):
                self.videoTrackItem.seek(self.playbackOffset)
                self.videoTrackItem.play()
            self.playWithSavedResults(self.playbackOffset)
        
    def pause(self):
        if self.isPlaying and not self.isPaused:
            self.isPaused = True
            #self.playbackOffset = self.currentChunkIndex * self.chunk_duration
            pygame.mixer.music.pause()
            if hasattr(self, "videoTrackItem"):
                self.videoTrackItem.pause()
        
            print(f"Current chunk index {self.currentChunkIndex}")
            
    def restart(self):
        """Restart playback from the beginning."""
        self.currentChunkIndex = 0
        self.isPlaying = False
        self.updateCanvasForCurrentPosition(0)
        pygame.mixer.music.rewind()
        
    def rewind(self):
        self.currentChunkIndex = max(0, self.currentChunkIndex - 1)
        self.updateCanvasForCurrentPosition()
        
    def forward(self):
        """Skip forward by one second (one chunk)."""
        self.currentChunkIndex = min(len(self.chunks) - 1, self.currentChunkIndex + 1)
        self.updateCanvasForCurrentPosition()
    
    def playWithSavedResults(self, startTimeMs):
        """Replay the audio with saved detection results synced to the audio."""
        if self.isPaused and not self.isManualUpdate: 
            #print('Application is paused')
            return
        
        if not self.isPlaying or self.isManualUpdate:
            try:
                if not self.isPlaying:
                    pygame.mixer.music.load(self.testSongPath)
                pygame.mixer.music.play(start=startTimeMs / 1000)
            except pygame.error as e:
                print(f"Error loading audio file: {e}")
                self.isPlaying = False
                return

            self.playbackOffset = startTimeMs
            self.currentChunkIndex = int(startTimeMs / self.chunk_duration)
            self.isPlaying = True
            self.isPaused = False
            self.isManualUpdate = False
        
        def updateChunk():
            if not self.isPlaying or self.isManualUpdate: 
                return
        
            # Get current playback position in milliseconds
            playbackPos = pygame.mixer.music.get_pos()
            if playbackPos == -1:
                print("Playback not started or stopped unexpectedly.")
                self.isPlaying = False
                return
            playbackTime = self.playbackOffset + playbackPos
            self.currentChunkIndex = int(playbackTime / self.chunk_duration)
            self.updateChunkText(self.currentChunkIndex)
            self.updateProgressBarHandle(playbackTime) # This was working
            self.updateDisplayedTime(playbackTime)
            self.updateCanvasForCurrentPosition(self.currentChunkIndex)
            
            # Update UI for voice detection
            if len(self.detectionResults) > 0:
                for member, trackItem in self.memberImages.items():
                    isVoiceDetected = self.detectionResults[self.currentChunkIndex].get(member, False)
                    if isVoiceDetected:
                        trackItem.currentImageKey = "light"
                    else:
                        trackItem.currentImageKey = "dark"
                    
                    # Update the canvas with the current image
                    imageId = self.memberImageIds[member]
                    self.canvas.itemconfig(imageId, image=trackItem.sourceImages[trackItem.currentImageKey])
                
            if self.currentChunkIndex >= len(self.chunks):
                self.pause()

            # Schedule the next chunk update
            self.root.after(self.chunk_duration, updateChunk)

        # Start updating chunks
        updateChunk()
    # end playWIthSavedResults
    
    def addMarkerToSection(self, chunkIndex, markerType):
        """
        Add a single marker to the appropriate sectionIndex key in timeMarkers and update marker dictionaries.
        """
        sectionIndex = chunkIndex // self.zoomManager.currentChunksInView
        if sectionIndex not in self.timeMarkers:
            self.timeMarkers[sectionIndex] = []
            
        self.timeMarkers[sectionIndex].append((markerType, chunkIndex))
        
        # Draw the marker and update the respective marker dictionary
        if markerType == "start":
            if chunkIndex not in self.startPointMarkers:
                self.startPointMarkers[chunkIndex] = self.canvas.create_line(
                    self.progressBarCanvas.winfo_x() + (chunkIndex % self.zoomManager.currentChunksInView / self.zoomManager.currentChunksInView) * self.progressBarWidth,
                    self.progressBarCanvas.winfo_y() - 20,
                    self.progressBarCanvas.winfo_x() + (chunkIndex % self.zoomManager.currentChunksInView / self.zoomManager.currentChunksInView) * self.progressBarWidth,
                    self.progressBarCanvas.winfo_y(),
                    fill="green",
                    width=4,
                )
                print(f"Start marker added at chunk {chunkIndex}.")
        elif markerType == "end":
            if chunkIndex not in self.endPointMarkers:
                self.endPointMarkers[chunkIndex] = self.canvas.create_line(
                    self.progressBarCanvas.winfo_x() + (chunkIndex % self.zoomManager.currentChunksInView / self.zoomManager.currentChunksInView) * self.progressBarWidth,
                    self.progressBarCanvas.winfo_y() - 20,
                    self.progressBarCanvas.winfo_x() + (chunkIndex % self.zoomManager.currentChunksInView / self.zoomManager.currentChunksInView) * self.progressBarWidth,
                    self.progressBarCanvas.winfo_y(),
                    fill="red",
                    width=4,
                )
                print(f"End marker added at chunk {chunkIndex}.")
    
    def saveLabels(self, selectedGroup, testSongPath):
        # Get file name without extension
        fileNameWithoutExtension = os.path.splitext(os.path.basename(testSongPath))[0]
        
        labelFilePath = f"./saved_labels/{selectedGroup}/{fileNameWithoutExtension}_labels.json"
        directory = os.path.dirname(labelFilePath)
        if not os.path.exists(directory):
            os.makedirs(directory)
            
        existingLabels = []
        if os.path.exists(labelFilePath):
            with open(labelFilePath, 'r') as f:
                existingLabels = json.load(f)
        
        uniqueExistingLabels = {tuple(label) for label in existingLabels}
        newLabels = [label for label in self.labels if tuple(label) not in uniqueExistingLabels]
        combinedLabels = existingLabels + newLabels
        combinedLabels = sorted(combinedLabels, key = lambda label: label[1])
        
        with open(labelFilePath, "w") as f:
            json.dump(combinedLabels, f, indent=4)