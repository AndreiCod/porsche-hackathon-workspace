from ultralytics import YOLO
from PIL import Image
import mediapipe as mp
import numpy as np
import pandas as pd
import cv2
import os
import sys

import json

import pose_estimator
from classifier import classify_by_hip_distance

print("In inference.py")

# Get model name from file
with open('/home/rpy/lastModel.txt', 'r') as file:
    model_name = file.read().replace('\n', '')

# Load the model
model = YOLO(os.path.join("/home/rpy", model_name))

# Load utils
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_pose = mp.solutions.pose

# Read Image
source = Image.open(r"/home/rpy/images/src8.jpg")

results = model.predict(source=source, save=True)

crosswalks = []
persons = []
predicts_list = []
predicts_dict = {}

for idx, box in enumerate(results[0].boxes.boxes):
    if box[-1] == 1:
        x_min, y_min, x_max, y_max = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        crosswalks.append((x_min, y_min, x_max, y_max))
    elif box[-1] == 2:
        x_min, y_min, x_max, y_max = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        persons.append((x_min, y_min, x_max, y_max))

if len(crosswalks) == 0:
    predicts_list.append("nici un pericol\n")
elif len(crosswalks) == 1:
    predicts_list.append("crosswalk 1\n")
    if len(persons) == 0:
        predicts_list.append("nici un pericol\n")
        predicts_dict["crosswalk1"] = "nici un pericol"
    for idx, person in enumerate(persons):
        if crosswalks[0][0] < person[0] < crosswalks[0][2] and crosswalks[0][1] < person[3] < crosswalks[0][3]:
            predicts_dict[f"crosswalk1_person{idx}"] = "danger, pe trecere"
            predicts_list.append("danger, pe trecere\n")
        elif crosswalks[0][1] < person[3] + 15 or crosswalks[0][3] > person[3] - 15:
            if person[0] < crosswalks[0][2] + 350:
                # Get orientation :
                landmarks = pose_estimator.get_pose_landmarks(np.asarray(source)[persons[0][1]:persons[0][3], persons[0][0]:persons[0][2]])
                hips_label = classify_by_hip_distance(landmarks)
                if hips_label == "side":
                    predicts_list.append("warning, pe langa trecere\n")
                    predicts_dict[f"crosswalk1_person{idx}"] = "warning, pe langa trecere"
                else:
                    predicts_list.append("langa trecere, dar nu se uita in stanga sau dreapta\n")
                    predicts_dict[f"crosswalk1_person{idx}"] = "langa trecere, dar nu se uita in stanga sau dreapta"
        else:
            predicts_list.append("nici un pericol\n")
            predicts_dict[f"crosswalk1_person{idx}"] = "langa trecere, dar nu se uita in stanga sau dreapta"
elif len(crosswalks) > 1:
    for idx_crs, crosswalk in enumerate(crosswalks):
        predicts_list.append(f'crosswalk {idx_crs}:\n')
        if len(persons) == 0:
            predicts_list.append("nici un pericol\n")
            predicts_dict[f"crosswalk{idx_crs}"] = "nici un pericol"
        for idx_prs, person in enumerate(persons):
            if crosswalk[0] < person[0] < crosswalk[2] and crosswalk[1] < person[3] < crosswalk[3]:
                predicts_list.append("danger, pe trecere\n")
                predicts_dict[f"crosswalk{idx_crs}_person{idx_prs}"] = "danger, pe trecere"
            elif crosswalk[1] < person[3] + 15 or crosswalk[3] > person[3] - 15:
                if person[0] < crosswalk[2] + 350:
                    # Get orientation :
                    landmarks = pose_estimator.get_pose_landmarks(np.asarray(source)[persons[0][1]:persons[0][3], persons[0][0]:persons[0][2]])
                    hips_label = classify_by_hip_distance(landmarks)
                    if hips_label == "side":
                        predicts_list.append("warning, pe langa trecere\n")
                        predicts_dict[f"crosswalk{idx_crs}_person{idx_prs}"] = "warning, pe langa trecere"
                    else:
                        predicts_list.append("langa trecere, dar nu se uita in stanga sau dreapta\n")
                        predicts_dict[
                            f"crosswalk{idx_crs}_person{idx_prs}"] = "langa trecere, dar nu se uita in stanga sau dreapta"
            else:
                predicts_list.append("nici un pericol")
                predicts_dict[
                    f"crosswalk{idx_crs}_person{idx_prs}"] = "nici un pericol"

with open('image_out.json', 'w') as outfile:
    json.dump(predicts_dict, outfile)

file = open('image_out.txt', 'w')
file.writelines(predicts_list)
file.close()

