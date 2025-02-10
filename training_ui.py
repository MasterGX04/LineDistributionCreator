from InquirerPy import prompt
import os
import sys
import json
from audio_tester import loadMemberImages, loadModel, VoiceDetectionApp
import tkinter as tk
from voice_training import voiceTrainingMain
import tensorflow as tf
from audio_processing import ( 
    combineMemberVocals, convertToWav, extractAudioFeatures, buildPerceptronModel, segmentAndSaveAudio
)
import numpy as np
from VoiceTrainer import RLSSingerRecogAgent

groups = {
    "IVE": [{'name': 'Gaeul', 'color': '#0000ff'}, {'name': 'Yujin', 'color': '#ff00ff'}, {'name': 'Rei', 'color': '#65bd2b'}, {'name': 'Wonyoung', 'color': '#ff0000'}, {'name': 'Liz', 'color': '#00c3f5'}, {'name': 'Leeseo', 'color': '#aa9f00'}],
    "ITZY": [{'name': 'Yeji', 'color': '#ffff00'}, {'name': 'Lia', 'color': '#eb7d46'}, {'name': 'Ryujin', 'color': '#7d46eb'}, {'name': 'Chaeryeong', 'color': '#3232ff'}, {'name': 'Yuna', 'color': '#46eb7d'}]
}   

def chooseAction(): 
    actionQuestion = {
        "type": "list",
        "message": "Do you want to TRAIN or TEST a model?",
        "choices": ["Train", "Test", "Extract Song"],
        "name": "actionChoice"
    }
    actionAnswer = prompt(actionQuestion)
    return actionAnswer['actionChoice']
# End chooseAction

# Function to ask user for group and member selection
def chooseGroupAndMember():
    # Ask the user to choose a group
    groupQuestion = [
        {
            "type": "list",
            "message": "Choose a Kpop group (or go back):",
            "choices": list(groups.keys()) + ["Back"],
            "name": "groupChoice"
        }
    ]
    groupAnswer = prompt(groupQuestion)
    if groupAnswer['groupChoice'] == "Back":
        return "Back", None 
    
    selectedGroup = groupAnswer['groupChoice']
    
    memberMapping = {member['name']: member for member in groups[selectedGroup]}
    
    # Ask the user to choose a member from the selected group
    memberQuestion = [
        {
            "type": "list",
            "message": f"Choose a member from {selectedGroup} (or go back):",
            "choices": list(memberMapping.keys()) + ["Back"] + ["All"],
            "name": "memberChoice"
        }
    ]
    memberAnswer = prompt(memberQuestion)
    selectedMemberName = memberAnswer['memberChoice']
    if selectedMemberName == "Back":
        return "Back", None
    
    if selectedMemberName == "All":
        return selectedGroup, selectedMemberName
    return selectedGroup, memberMapping[selectedMemberName]
# End chooseGroupMember

def updateSongHistory(selectedGroup, selectedSong):
    """
    Updates the song history JSON file to move the most recently selected song to the top.
    Creates the file if it does not exist.
    
    :param selectedGroup: Name of the Kpop group.
    :param selectedSong: Name of the selected song without file extension.
    """
    jsonFilePath = f"./{selectedGroup}/saved_songs.json"
    
    os.makedirs(os.path.dirname(jsonFilePath), exist_ok=True)
    if os.path.exists(jsonFilePath):
        with open(jsonFilePath, "r", encoding="utf-8") as file:
            try:
                songHistory = json.load(file)
            except json.JSONDecodeError:
                songHistory = []
    else:
        songHistory = []
        
    songDir = f"./training_data/{selectedGroup}"
    allSongs = [f.replace(".mp3", "") for f in os.listdir(songDir) if f.endswith(".mp3") and "_vocals" not in f]
    
    # Add new MP3 files to the front of the list if they aren't in songHistory
    for song in reversed(allSongs):
        if song not in songHistory:
            songHistory.insert(0, song)
         
    songHistory = [song for song in songHistory if song != selectedSong]
    
    # Add the selected song at the top
    songHistory.insert(0, selectedSong)
    
    with open(jsonFilePath, "w", encoding="utf-8") as file:
        json.dump(songHistory, file, indent=4, ensure_ascii=False)

def chooseTestSong(groupName):
    songDir = f"./training_data/{groupName}"
    savedSongsFile = f"./{groupName}/saved_songs.json"
    allSongs = [f.replace(".mp3", "") for f in os.listdir(songDir) if f.endswith(".mp3") and "_vocals" not in f]
    
    # Initialize savedSongs from JSON if available, else store allSongs
    if os.path.exists(savedSongsFile):
        with open(savedSongsFile, "r", encoding="utf-8") as file:
            try:
                savedSongs = json.load(file)
            except json.JSONDecodeError:
                savedSongs = []
    else:
        savedSongs = []
        
    if not savedSongs:
        savedSongs = allSongs
    else:
        # Append any new songs that aren't in savedSongs
        for song in allSongs:
            if song not in savedSongs:
                savedSongs.append(song)  # Append new songs to the end

    # Save the updated list back to JSON
    with open(savedSongsFile, "w", encoding="utf-8") as file:
        json.dump(savedSongs, file, indent=4, ensure_ascii=False)
        
    if not savedSongs:
        print("No songs available for testing.")
        return None, None
    
    songQuestion = [
        {
            "type": "list",
            "message": f"Choose a song to test for {groupName}", 
            "choices": savedSongs + ["Back"],
            "name": "songChoice"
        }
    ]
    
    songAnswer = prompt(songQuestion)
    selectedSong = songAnswer['songChoice']
    
    if selectedSong == "Back":
        return selectedSong, None
    
    songPath = os.path.join(songDir, f"{selectedSong}.mp3")
    vocalsOnlyPath = os.path.join(songDir, f"{selectedSong}_vocals.mp3")
    
    if not os.path.exists(vocalsOnlyPath):
        print(f"Vocals-only version '{vocalsOnlyPath} not found")
        return songPath, songPath
    
    updateSongHistory(groupName, selectedSong)
    return songPath, vocalsOnlyPath
# End chooseTestSong

def loadLabels(jsonPath):
    """Load labeled data and dynamically check if a chunk is within a singer's range"""
    with open(jsonPath, "r") as file:
        labels = json.load(file)

    # ✅ Store singers in a list of (startChunk, endChunk)
    chunkRanges = []
    for entry in labels:
        singer, start, end = entry
        chunkRanges.append((singer, start, end))

    return chunkRanges 

def prepareTrainingData(selectedGroup, selectedMember):
    """Train and save a TensorFlow model for a specific member"""
    mp3Path = f"./training_data/{selectedGroup}/{selectedMember}_training_vocals.mp3"
    wavPath = f"./training_data/{selectedGroup}/{selectedMember}_training_vocals.wav"
    saveDir = f"./{selectedGroup}/{selectedMember}/train/data"
    os.makedirs(saveDir, exist_ok=True)
    savePath = f"{saveDir}/{selectedMember}_chunks.npy"
    
    if not os.path.exists(mp3Path):
        print(f"Training audio not found for {selectedMember}.")
        return None
    
    # Convert mp3 to wav
    convertToWav(mp3Path, wavPath)
    
    # Extract features from WAV file
    features = segmentAndSaveAudio(wavPath, savePath, segmentDuration=200)
    
    print(f"Features extracted from {selectedMember}_training_vocals.wav")
    
    negativeFeatures = []
    for otherMember in [m["name"] for m in groups[selectedGroup] if m["name"] != selectedMember]:
        otherPath = f"./training_data/{selectedGroup}/{otherMember}_training_vocals.mp3"
        otherWavPath = f"./training_data/{selectedGroup}/{otherMember}_training_vocals.wav"
        otherSaveDir = f"./{selectedGroup}/{otherMember}/train/data"
        os.makedirs(otherSaveDir, exist_ok=True)
        otherSavePath = f"{otherSaveDir}/{otherMember}_chunks.npy"
        if os.path.exists(otherPath):
            convertToWav(otherPath, otherWavPath)
            negFeatures = segmentAndSaveAudio(otherWavPath, otherSavePath, segmentDuration=200)
            negativeFeatures.append(negFeatures)
            print(f"Negative features extracted from {otherMember}")
            
    X_train = np.vstack((features, *negativeFeatures))  # Combine features
    y_train = np.array([ [1, 0] ] * len(features) + [ [0, 1] ] * sum(len(n) for n in negativeFeatures))
    
    indices = np.arange(len(X_train))
    np.random.shuffle(indices)
    X_train, y_train = X_train[indices], y_train[indices]
    
    # Build perceptron model
    model = buildPerceptronModel(features.shape[1:], numMembers=2)
    print(f"Model for {selectedMember} created!")
    
    # Train the model
    model.fit(X_train, y_train, epochs=50, batch_size=32)
    
    #model.fit(X_train, y_train, epochs=10, batch_size=32)
    
    modelSavePath = f"./{selectedGroup}/{selectedMember}/train/data"
    os.makedirs(modelSavePath, exist_ok=True)
    modelPath = f"{modelSavePath}/{selectedMember}_model.h5"
    
    # Save the trained model
    model.save(modelPath)
    print(f"Model saved at: {modelPath}")
    
    return modelPath

def trainRLAgent(selectedGroup, selectedMember, modelPath):
    """Train RL agent using labeled song data"""
    labelsDir = f"./saved_labels/{selectedGroup}"
    
    if not os.path.exists(labelsDir):
        print(f"No labeled data found for {selectedGroup}.")
        return

    labelFiles = [f for f in os.listdir(labelsDir) if f.endswith("_labels.json")]
    if not labelFiles:
        print(f"No labeled song data found in {labelsDir}.")
        return
    
    rlModelPath = f"./{selectedGroup}/{selectedMember}/train/data/rl_{selectedMember}.h5"
    metricsPath = f"./{selectedGroup}/{selectedMember}/train/data/rl_{selectedMember}_metrics.csv"
    # Initialize RL agent
    agent = RLSSingerRecogAgent([selectedMember], modelPath, rlModelPath, metricsPath)
    
    for labelFile in labelFiles:
        songName = labelFile.replace("_labels.json", "")
        print(f"Training {selectedMember} with {songName}")
        jsonPath = os.path.join(labelsDir, labelFile)
        labels = loadLabels(jsonPath)
        # print("Labels:", labels)

        songPath = f"./training_data/{selectedGroup}/{songName}_vocals.mp3"
        wavPath = f"./training_data/{selectedGroup}/{songName}_vocals.wav"
        convertToWav(songPath, wavPath)
        if not os.path.exists(wavPath):
            print(f"Skipping {songName} (missing vocals file).")
            continue
        
        # Train RL agent
        agent.trainAgent(labels, wavPath, songName)

# main functin to start process
def main():
    while True:
        action = chooseAction()
        
        if action == "Test":
            while True:
                selectedGroup, selectedMember = chooseGroupAndMember()
                if selectedGroup == "Back": break
                
                while True:
                    testSongPath,  vocalsOnlyPath = chooseTestSong(selectedGroup)
                    print(f"Test song path: {testSongPath}")
                    if testSongPath == "Back":
                        break
                    
                    if not testSongPath or not vocalsOnlyPath:
                        print("No valid test song selected. Returning to group selection.")
                        continue  # Allow going back to group selection
                    
                    if testSongPath and vocalsOnlyPath:
                        model = loadModel(selectedGroup, selectedMember['name'])
                        images = loadMemberImages(selectedGroup, groups[selectedGroup], testSongPath)
                        
                        if model:
                            root = tk.Tk()
                            continueApp = [True]
                            app = None

                            def onClose():
                                if tk.messagebox.askyesno("Exit", "Do you want to stop the application?"):
                                    if hasattr(app, "videoTrackItem") and app.videoTrackItem:
                                        app.videoTrackItem.pause()
                                        app.videoTrackItem.stop()  
                                    continueApp[0] = False
                                    root.destroy()
                                    sys.exit()
                                else:
                                    if tk.messagebox.askyesno("Switch Member/Group", "Do you want to switch to a different member or group?"):
                                        if hasattr(app, "videoTrackItem") and app.videoTrackItem:
                                            app.videoTrackItem.stop()  
                                        continueApp[0] = False
                                        root.destroy()
                                    
                            root.protocol("WM_DELETE_WINDOW", onClose)  # Close current app and return to selection

                            app = VoiceDetectionApp(root, selectedMember, groups[selectedGroup], model, images, testSongPath, vocalsOnlyPath, selectedGroup)
                            
                            if hasattr(app, "videoTrackItem") and app.videoTrackItem and app.videoTrackItem.thread:
                                app.videoTrackItem.thread.daemon = True
                                
                            root.mainloop()
                            
                            if not continueApp[0]:
                                break
                        else:
                            print(f"No trained model found for {selectedMember['name']}. Please train a model first.")
                    break
        elif action == "Train":
            while True:
                selectedGroup, selectedMember = chooseGroupAndMember()
                
                if selectedGroup == "Back":
                    break
                
                if selectedMember == "All":
                    for member in groups[selectedGroup]:
                        memberName = member["name"]
                        print(f"\n🚀 Training {memberName} in {selectedGroup}...\n")

                        # ✅ Train model for the member
                        modelPath = prepareTrainingData(selectedGroup, memberName)

                        # ✅ Train RL agent for the member
                        if modelPath:
                            trainRLAgent(selectedGroup, memberName, modelPath)

                    print("\n✅ All members trained successfully!\n")
                    break  # ✅ Exit after training all members
                                
                memberName = selectedMember["name"]
                # Train TensorFlow model for the member
                modelSavePath = f"./{selectedGroup}/{memberName}/train/data"
                modelPath = f"{modelSavePath}/{memberName}_model.h5"
                
                if os.path.exists(modelPath):
                    print(f"Model already exists at: {modelPath}")
                    confirmReplace = prompt({
                        "type": "confirm",
                        "message": f"Do you want to replace the existing model for {memberName}?",
                        "name": "replaceModel",
                        "default": False
                    })["replaceModel"]

                    if confirmReplace:  # ✅ If user chooses to retrain, delete old model
                        os.remove(modelPath)
                        print(f"Deleted existing model for {memberName}. Retraining now...")
                        modelPath = prepareTrainingData(selectedGroup, memberName)  # ✅ Retrain model
                    else:
                        print(f"Using existing model for {memberName}.")
                else:
                    modelPath = prepareTrainingData(selectedGroup, memberName)  # ✅ Train model if it doesn't exist
                        
                if modelPath:
                    trainRLAgent(selectedGroup, memberName, modelPath)
                break
        elif action == "Extract Song":
            while True:
                groupQuestion = [
                    {
                        "type": "list",
                        "message": "Choose a Kpop group to extract a song from:",
                        "choices": list(groups.keys()) + ["Back"],
                        "name": "groupChoice"
                    }
                ]
                groupAnswer = prompt(groupQuestion)
                selectedGroup = groupAnswer['groupChoice']
                
                if selectedGroup == "Back":
                    break
                vocalsPath = f"./training_data/{selectedGroup}"
                vocalsOnly = [f for f in os.listdir(vocalsPath) if (f.endswith(".mp3") or f.endswith(".wav")) and "_vocals" in f]
                
                if not vocalsOnly:
                    print("No songs available for testing.")
                    return None
                
                groupJSONPath = f"./saved_labels/{selectedGroup}"
                groupJSONFiles = [os.path.join(groupJSONPath, f) for f in os.listdir(groupJSONPath) if f.endswith(".json")]
                
                combineMemberVocals(groupJSONFiles, vocalsOnly, selectedGroup)
                break
        # end while
#end main

if __name__ == "__main__":
    main()