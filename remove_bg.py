from rembg import remove
from PIL import Image
import os

robot_path = r"e:\Agent 14\new_agent_14_fe\public\avatars\robot.jpg"
human_path = r"e:\Agent 14\new_agent_14_fe\public\avatars\human.jpg"

out_robot = r"e:\Agent 14\new_agent_14_fe\public\avatars\robot_transparent.png"
out_human = r"e:\Agent 14\new_agent_14_fe\public\avatars\human_transparent.png"

def process_img(in_path, out_path):
    if not os.path.exists(in_path):
        print(f"File not found: {in_path}")
        return
    
    print(f"Processing {in_path}...")
    input_img = Image.open(in_path)
    output_img = remove(input_img)
    output_img.save(out_path)
    print(f"Saved {out_path}")

process_img(robot_path, out_robot)
process_img(human_path, out_human)
print("Done!")
