import os
import json
from pydub import AudioSegment
import librosa
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Flatten, Input
from concurrent.futures import ThreadPoolExecutor
import numpy as np

CHUNK_DURATION = 40

def convertToWav(inputMp3Path, outputWavPath):
    audio = AudioSegment.from_mp3(inputMp3Path)
    audio.export(outputWavPath, format="wav")
    
def extractFeatures(audioPath, sr=22050):
    """Extracts features for the full duration of the training audio"""
    y, sr = librosa.load(audioPath, sr=sr)

    # Extract MFCC, Mel Spectrogram, and Chroma features
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    melSpec = librosa.feature.melspectrogram(y=y, sr=sr)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)

    # Stack features along time axis
    features = np.vstack((mfcc, melSpec, chroma)).T

    return features  # Shape: (Time-steps, Feature-dim)

def combineMemberVocals(jsonFiles, vocalsOnlySongs, selectedGroup):
    outputDir = f"./training_data/{selectedGroup}"
    os.makedirs(outputDir, exist_ok=True)
    
    memberAudioSegments = {}
    
    jsonFileMap = {os.path.splitext(os.path.basename(f))[0].replace("_labels", ""): f for f in jsonFiles}
    
    for vocalsFile in vocalsOnlySongs:
        songTitle = os.path.basename(vocalsFile).replace("_vocals.mp3", "").replace("_vocals.wav", "")
        print(f"Extracting vocals from {songTitle}")
        jsonFilePath = jsonFileMap.get(songTitle)
        
        if not jsonFilePath:
            print(f"Warning: No matching JSON file found for {songTitle}. Skipping.")
            continue

        with open(jsonFilePath, 'r') as file:
            labels = json.load(file)
            
        vocalsPath = os.path.join(f"./training_data/{selectedGroup}", vocalsFile)
        vocals = AudioSegment.from_file(vocalsPath)
        
        for label in labels:
            memberName, startChunk, endChunk = label
            if memberName not in memberAudioSegments:
                memberAudioSegments[memberName] = AudioSegment.silent(duration=0)
            
            # Extract relevant portion of vocals
            startTime = startChunk * CHUNK_DURATION
            endTime = (endChunk - 1) * CHUNK_DURATION
            memberAudioSegments[memberName] += vocals[startTime:endTime]
            
    for memberName, audioSegment in memberAudioSegments.items():
        outputFile = os.path.join(outputDir, f"{memberName}_training_vocals.mp3")
        if os.path.exists(outputFile):
            existingAudio = AudioSegment.from_file(outputFile)
            audioSegment = existingAudio + audioSegment
            
        audioSegment.export(outputFile, format="mp3")
        print(f"Saved {outputFile}")
        
def segmentAndSaveAudio(audioPath, savePath='', segmentDuration=200):
    """Segment the audio into fixed 40ms chunks and extract features per chunk"""
    
    if os.path.exists(savePath) and savePath != '':  # ✅ Skip processing if file already exists
        print(f"Loading precomputed chunks from {savePath}")
        return np.load(savePath)
    
    print(f"Extracting audio chunks from {audioPath}...")
    y, sr = librosa.load(audioPath, sr=22050)
    if len(y) == 0:
        raise ValueError(f"Error: Loaded empty audio from {audioPath}")
    
    segmentSamples = int(sr * (segmentDuration / 1000.0))  # 40ms worth of samples
    chunks = [y[i: i + segmentSamples] for i in range(0, len(y), segmentSamples)]
    
    # Convert each chunk into features
    featureChunks = []
    
    for chunk in chunks:
        if len(chunk) < segmentSamples:  # Ensure chunk is full length
            chunk = np.pad(chunk, (0, segmentSamples - len(chunk)))
        
        # Set `n_fft` dynamically to be the nearest power of 2
        n_fft = 1024 if segmentSamples >= 1024 else 512

        # Extract MFCC, Chroma, and Mel Spectrogram for this chunk
        mfcc = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=13, n_fft=n_fft)
        melSpec = librosa.feature.melspectrogram(y=chunk, sr=sr, n_fft=n_fft)
        chroma = librosa.feature.chroma_stft(y=chunk, sr=sr, n_fft=n_fft)

        # Stack features along feature-dim (total = 13+128+12 = 153)
        featureMatrix = np.vstack((mfcc, melSpec, chroma))  # Shape: (153, time-steps)
        featureMatrix = featureMatrix.T  # Shape: (time-steps, 153)

        featureChunks.append(featureMatrix)
    
    np.save(savePath, featureChunks)
    print(f"Saved chunks to {savePath}")
    return np.array(featureChunks)

def buildPerceptronModel(inputShape, numMembers=1):
    print(f"Perceptron shape: {inputShape}")
    model = Sequential([
        Input(shape=inputShape),  # Dynamic time-steps
        Flatten(),
        Dense(128, activation="relu"),
        Dense(64, activation="relu"),
        Dense(numMembers, activation="sigmoid")  # Multi-class classification
    ])
    
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    return model

def extractAudioFeatures(audioPath, sr=22050, maxDuration=6.0):
    y, sr = librosa.load(audioPath, sr=sr)
    duration = librosa.get_duration(y=y, sr=sr)
    
    # Limit to max duration (e.g., 6 seconds) for consistency
    if duration > maxDuration:
        y = y[:int(sr * maxDuration)]
    
    # Extract MFCCs, Mel Spectrogram, and Chroma Features
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    melSpec = librosa.feature.melspectrogram(y=y, sr=sr)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)

    # Stack features together
    features = np.vstack((mfcc, melSpec, chroma))
    return features.T  # Transpose to match input format
        
def getSongsFromSameAlbum():
    songsFromSameAlbum = {
        'IVE': {
            'Accendio': ['해야 (HEYA)', 'Accendio', 'Blue Blood', 'Summer Festa', "Blue Heart", "Hypnosis", "WOW", "My Satisfaction"],
            'ATTITUDE': ['Rebel Heart', 'Flu', 'You Wanna Cry', 'ATTITUDE','Thank U', 'TKO', 'Mine']}
    }
    
    return songsFromSameAlbum

def getVoiceDetectionArray(model, totalChunks, audioSegments):
    detectionArray = [0] * (totalChunks + 1) # Track 40ms per chunk responsees
    
    def processSegment(segmentIndex):
        # Ensure input shape matches model expectation
        segment = audioSegments[segmentIndex]
        if len(segment.shape) == 2:
            segment = np.expand_dims(segment, axis=0)  
        
        # Predict singer probabilities
        prediction = model.predict(segment)[0]         
        
        chunkStart = segmentIndex * 5
        
        for i in range(5):
            chunkIndex = chunkStart + i
            if chunkIndex < totalChunks:
                detectionArray[chunkIndex] = 1 if prediction[0] > 0.8 else 0   
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(processSegment, range(len(audioSegments))))
       
    return detectionArray