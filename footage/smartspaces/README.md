# NVIDIA PhysicalAI-SmartSpaces: scene 081 (hospital)

Source: https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces
(`MTMC_Tracking_2024/test/scene_081`). Licence: CC-BY-4.0. Synthetic (NVIDIA Omniverse).

Four of the scene's 16 cameras, chosen because no person is ever in two of them at
once (0% overlap) while people walk between them often (444 walks, all 37 people):

| Camera | Area | Links to |
|---|---|---|
| 796 | East wing corridor | 803 (median gap 5.5 s) |
| 803 | Reception / lobby | 796, 800 (6.5 s) |
| 800 | Main corridor | 803, 804 (2 s) |
| 804 | Waiting alcove | 800 |

All four videos: 1920x1080, 30 fps, 23,994 frames (13.3 min), time-synchronised.

`ground_truth.txt` (all 16 cameras, MOTChallenge style), one line per box:
`camera_id person_id frame x y w h world_x world_y`. person_id is the same person in
every camera, so it is the ground truth for cross-zone journeys. world_x/y are floor
positions in metres.

Previews: `preview_cameras.jpg` (one moment, all four cameras) and `preview_map.png`
(where each camera sees people on the floor plan).
