import numpy as np

class RLSSingerRecogAgent:
    def __init__(self):
        self.points = 0
        self.actions = []
        
    def addSinger(self, singer):
        if singer not in self.actions:
            self.actions.append(singer)
            
    # Add more stuff later
    def guess(self, features):
        # Dummy logic for guessing (can be replaced with a proper RL policy)
        return np.random.choice(self.actions)
    
    def reward(self, correct):
        if correct:
            self.points += 1  # Reward for correct guess
        else:
            self.points -= 1  # Penalty for incorrect guess
    
    def getPoints(self):
        return self.points 