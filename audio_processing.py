import numpy as np
import os
from InquirerPy import prompt
import json
from pydub import AudioSegment
from pydub.utils import make_chunks
import tkinter as tk
from tkinter import messagebox

def calculateFrameEnergy(audioFrame):
    """Calculate energy of an audio frame."""
    return np.mean(np.abs(np.array(audioFrame.get_array_of_samples())))

def calibrateThreshold(audio, frameRate=24, calibrationDuration=1):
    """
    Calibrate the silence threshold by analyzing the quietest portion of the audio.
    """
    calibrationFrames = make_chunks(audio[:calibrationDuration * 1000], 1000 / frameRate)
    energies = [calculateFrameEnergy(frame) for frame in calibrationFrames]
    print("Energies:", energies)
    baselineEnergy = np.percentile(energies, 10)
    return baselineEnergy * 2

def processAudioFile(audioPath, frameRate=24, silenceThreshold=None):
    """Process audio into binary frames"""
    audio = AudioSegment.from_file(audioPath)
    frameDuration = 1000 / frameRate
    
    if silenceThreshold is None:
        silenceThreshold = calibrateThreshold(audio, frameRate)
        print(f"Calibrated silence threshold: {silenceThreshold:.4f}")
        
    frames = make_chunks(audio, frameDuration)
    binaryArray = []
    for frame in frames:
        energy = calculateFrameEnergy(frame)
        binaryArray.append(1 if energy > silenceThreshold else 0)
        
    return binaryArray, frames

def findMusicResidues(binaryArray, residueThreshold=5):
    residues = []
    for i in range(1, len(binaryArray) - residueThreshold - 1):
        if binaryArray[i:i+residueThreshold] == [1] * residueThreshold and binaryArray[i-1] == binaryArray[i+residueThreshold] == 0:
            residues.append((i, i + residueThreshold + i))
    return residues

def userResolveResidues(binaryArray, residues, frames):
    root = tk.Tk()
    root.withdraw()
    for start, end in residues:
        result = messagebox.askquestion(
            "Music Residue Detected",
            f"Residue detected in frames {start} to {end}. Set to 0?",
            icon = "warning"
        )
        if result == 'yes':
            for i in range(start, end + 1):
                binaryArray[i] = 0
    root.destroy()
    
def saveBinaryArrayToJson(binaryArray, audioPath):
    """Save binary array to a JSON file based on audio file name"""
    baseName = os.path.splitext(os.path.basename(audioPath))[0]
    outputDir = "./audio_extraction"
    os.makedirs(outputDir, exist_ok=True)
    
    jsonFilePath = os.path.join(outputDir, f"{baseName}.json")
    
    # Save binary to JSON
    with open(jsonFilePath, "w") as jsonFile:
        json.dump(binaryArray, jsonFile, indent=4)
    
    print(f"Binary array saved to {jsonFilePath}")
    
def extractSong(groupName):
    """Process and extract binary audio data for a song"""
    songDir = f"./training_data/{groupName}"
    songs = {f for f in os.listdir(songDir) if (f.endswith(".mp3") or f.endswith("wav")) and "_vocals" in f}
    
    if not songs:
        print(f"No songs available in directory: '{songDir}")
        return
    
    # Ask user to choose song
    songQuestion = [
        {
            "type": "list",
            "message": "Choose a song to process:",
            "choices": songs,
            "name": "songChoice"
        }
    ]
    
    songAnswer = prompt(songQuestion)
    selectedSong = songAnswer['songChoice']
    songPath = os.path.join(songDir, selectedSong)
    
    # Process the song
    print(f"Processing song: {selectedSong}")
    binaryArray, frames = processAudioFile(songPath)
    residues = findMusicResidues(binaryArray)
    
    if residues:
        print(f"Music residues detected: {residues}")
        userResolveResidues(binaryArray, residues, frames)
    
    # Save binary array to JSON
    saveBinaryArrayToJson(binaryArray, songPath)
    print(f"Song processing complete. Data saved for {selectedSong}")       