import os
import librosa
import numpy as np
import soundfile as sf
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.models import load_model
from tensorflow.keras.callbacks import ModelCheckpoint
from tensorflow.keras.layers import Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.utils import to_categorical

def extractFeatures(filePath):
    try:
        audio, sr = librosa.load(filePath, sr=None)

        #Extract MFCC
        mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
        
        #extract chroma
        chroma = librosa.feature.chroma_stft(y=audio, sr=sr)
        
        #Extract spectral contrast
        spectralConstrast = librosa.feature.spectral_contrast(y=audio, sr=sr)
        
        #stack all features in one array
        features = np.hstack([np.mean(mfcc, axis=1), np.mean(chroma, axis=1), np.mean(spectralConstrast, axis=1)])
        return features
    except Exception as e:
        print(f"Error encountered while parsing file: {filePath}")
        return None
# End extractFeatures

# Process all audio files in selected directory
def loadTrainingData(vocalsPath):
    featuresList = []
    
    for fileName in os.listdir(vocalsPath):
        if fileName.endswith(".mp3"):
            filePath = os.path.join(vocalsPath, fileName)
            print(f"Proceessing {filePath}")
            features = extractFeatures(filePath)
            
            #If successfully extracted, append
            if features is not None:
                featuresList.append(features)
    # end for
    return np.array(featuresList)
# End loadTrainingData

# Function to prepare data using features extracted from 'loadTrainingData'
def prepareDataForSinger(features):
    labels = np.ones((features.shape[0], 1))
    
    #Split into ttraining and testing sets 
    xTrain, xTest, yTrain, yTest = train_test_split(features, labels, test_size=0.2, random_state=42)
    
    #Normalize features
    scaler = StandardScaler()
    xTrainScaled = scaler.fit_transform(xTrain)
    xTestScaled = scaler.transform(xTest)
    
    return xTrainScaled, xTestScaled, yTrain, yTest
    
#build CNN model
def buildCnnModel(inputShape):
    model = Sequential([
        Conv2D(32, kernel_size=(1, 1), activation='relu', input_shape=inputShape),
        MaxPooling2D(pool_size=(1, 1)),
        Flatten(),
        Dense(64, activation='relu'),
        Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model
# end buildCnnModel

def saveTrainingData(model, testAccuracy, testLoss, dataPath, selectedMember):
    if not os.path.exists(dataPath):
        os.makedirs(dataPath)
    
    # Save the model
    modelSavePath = os.path.join(dataPath, f"{selectedMember}_model.h5")
    model.save(modelSavePath)
    print(f"Model saved to {modelSavePath}")
    
    # Save test data (loss and accuracy)
    testDataSavePath = os.path.join(dataPath, f"{selectedMember}_training_data.npy")
    np.save(testDataSavePath, np.array([testLoss, testAccuracy]))
    print(f"Test data saved to {testDataSavePath}")
#end saveTrainingData

def loadAndDisplaySavedData(dataPath, selectedMember):
    modelSavePath = os.path.join(dataPath, f"{selectedMember}_model.h5")
    testDataSavePath = os.path.join(dataPath, f"{selectedMember}_training_data.npy")
    
    if os.path.exists(modelSavePath) and os.path.exists(testDataSavePath):
        print(f"Loading model and test data for {selectedMember}...")
        
        # Load model
        model = load_model(modelSavePath) # Will be used later
        print(f"Model loaded from {modelSavePath}")
        
        testData = np.load(testDataSavePath)
        testLoss, testAccuracy = testData[0], testData[1]
        print(f"Test loss: {testLoss:.4f}, Test accuracy: {testAccuracy * 100:.2f}%")

        return True
    # end if
    return False
# end loadAndDisplaySavedData

def voiceTrainingMain(vocalsPath, selectedMember):
    
    if os.path.exists(vocalsPath):
        dataPath = os.path.join(os.path.dirname(vocalsPath), "data")
        
        if loadAndDisplaySavedData(dataPath, selectedMember):
            print(f"Training data for {selectedMember} already exists. Displaying results.")
        else:   
            print(f"Extracting features from directory: {vocalsPath}")
            features = loadTrainingData(vocalsPath)
            print(f"Feature extraction complete. Extracted features shape: {features.shape}")
            
            xTrain, xTest, yTrain, yTest = prepareDataForSinger(features)

            # Reshape the data to match the input shape required by Conv2D
            xTrain = np.expand_dims(xTrain, axis=-1)  # Add a dimension for width (1)
            xTrain = np.expand_dims(xTrain, axis=-1)  # Add a dimension for channels (1)
            
            xTest = np.expand_dims(xTest, axis=-1)    # Same for test data
            xTest = np.expand_dims(xTest, axis=-1)

            inputShape = (xTrain.shape[1], 1, 1)  # Adjusted input shape for CNN
            model = buildCnnModel(inputShape)
            
            #Train model
            model.fit(xTrain, yTrain, validation_data=(xTest, yTest), epochs=15, batch_size=32)
            
            # Evaluate model on test data
            testLoss, testAccuracy = model.evaluate(xTest, yTest)
            print(f"Test accuracy for {selectedMember}: {testAccuracy * 100:.2f}")
            
            saveTrainingData(model, testLoss, testAccuracy, dataPath, selectedMember)
    else:
        print(f"Directory {vocalsPath} does not exist.")
# end main