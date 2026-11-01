import pandas as pd
import numpy as np
import xgboost as xgb
import pickle

print("Generating synthetic campus traffic data...")
# Features: hour (8-18), location_id (0-4), is_event (0-1)
data = []
for _ in range(500):
    hour = np.random.randint(8, 19)
    loc = np.random.randint(0, 5)
    event = np.random.choice([0, 1], p=[0.8, 0.2]) # 20% chance of an event
    
    # Logic to make the fake data realistic
    crowd = 0 # 0: Low, 1: Medium, 2: High
    if event == 1:
        crowd = 2
    elif loc == 4 and (12 <= hour <= 14): # Canteen at lunch
        crowd = 2
    elif loc == 0 and (hour == 8 or hour == 17): # Main gate at start/end of day
        crowd = 2
    elif loc == 2 and (9 <= hour <= 15): # CS block during classes
        crowd = 1
    
    data.append([hour, loc, event, crowd])

df = pd.DataFrame(data, columns=['hour', 'location_id', 'is_event', 'crowd_level'])

print("Training XGBoost Model...")
X = df[['hour', 'location_id', 'is_event']]
y = df['crowd_level']

model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='mlogloss')
model.fit(X, y)

with open("crowd_model.pkl", "wb") as f:
    pickle.dump(model, f)

print("✅ Success! Model saved as 'crowd_model.pkl'.")