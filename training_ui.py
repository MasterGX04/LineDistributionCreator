from InquirerPy import prompt
import os
import sys
from audio_tester import loadMemberImages, loadModel, VoiceDetectionApp
import tkinter as tk
from voice_training import voiceTrainingMain
from audio_processing import extractSong

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
            "choices": list(memberMapping.keys()) + ["Back"],
            "name": "memberChoice"
        }
    ]
    memberAnswer = prompt(memberQuestion)
    selectedMemberName = memberAnswer['memberChoice']
    if selectedMemberName == "Back":
        return "Back", None

    return selectedGroup, memberMapping[selectedMemberName]
# End chooseGroupMember

def chooseTestSong(groupName):
    songDir = f"./training_data/{groupName}"
    songs = [f for f in os.listdir(songDir) if (f.endswith(".mp3") or f.endswith(".wav")) and "_vocals" not in f]
    
    if not songs:
        print("No songs available for testing.")
        return None
    
    songQuestion = [
        {
            "type": "list",
            "message": f"Choose a song to test for {groupName}", 
            "choices": songs + ["Back"],
            "name": "songChoice"
        }
    ]
    
    songAnswer = prompt(songQuestion)
    selectedSong = songAnswer['songChoice']
    if selectedSong == "Back":
        return selectedSong, None
    songPath = os.path.join(songDir, selectedSong)
    vocalsOnlyPath = os.path.join(songDir, selectedSong.replace(".mp3", "_vocals.mp3").replace(".wav", "_vocals.wav"))
    
    if not os.path.exists(vocalsOnlyPath):
        print(f"Vocals-only version '{vocalsOnlyPath} not found")
        return songPath, songPath
    return songPath, vocalsOnlyPath
# End chooseTestSong

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
                        images = loadMemberImages(selectedGroup, groups[selectedGroup])
                        
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
                
                vocalsPath = f"./{selectedGroup}/{selectedMember}/train/Isolated_Vocals"
                voiceTrainingMain(vocalsPath, selectedMember)
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
                
                extractSong(selectedGroup)
                break
        # end while
#end main

if __name__ == "__main__":
    main()