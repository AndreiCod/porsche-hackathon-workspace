import numpy as np

import mediapipe as mp

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_pose = mp.solutions.pose


def get_hips_distance(landmarks):
    """Return the distance between the hips.

    Args:
        landmarks (np.ndarray): The pose landmarks for the given image.

    Returns:
        float: The distance between the hips.
    """
    # Get the landmarks for the hips
    hip_left = landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP.value]
    hip_right = landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP.value]

    # Calculate the distance between the hips only on the x axis
    distance = abs(hip_left.x - hip_right.x)
    # print(distance)
    return distance


def classify_by_hip_distance(landmarks, threshold=0.2):
    """Classify the pedestrian orientation based on the distance between the hips.

    Args:
        landmarks (np.ndarray): The pose landmarks for the given image.
        threshold (float, optional): The threshold to use for the classification. Defaults to 0.1.

    Returns:
        str: The orientation of the pedestrian.
    """
    # Get the distance between the hips
    hip_distance = get_hips_distance(landmarks)

    # Classify the pedestrian orientation
    if hip_distance < threshold:
        return "side"
    else:
        return "front"
