# Footage

Test footage for the corridor people counter. Video files are not tracked in
git; fetch them with:

```
.venv/bin/python scripts/download_footage.py
```

## CAVIAR corridor-view clips (`caviar/`)

- EnterExitCrossingPaths1cor
- ThreePastShop1cor
- OneShopOneWait2cor
- OneStopMoveEnter1cor
- WalkByShop1cor
- ShopAssistant2cor

Ground-truth XML for each clip is in `caviar/gt/`.

**Credit:** EC Funded CAVIAR project/IST 2001 37540, http://homepages.inf.ed.ac.uk/rbf/CAVIAR/

**Licence:** CC BY-SA

## MEVA (`meva/`)

- `contact_sheet.jpg` / `cameras.csv`: one frame per camera for one hour,
  built with `.venv/bin/python scripts/meva_survey.py`
- `activity.csv` / `activity_windows.csv`: people per frame (YOLO11n, every 5 s)
  for the five dashboard cameras over 2018-03-12 10:00-11:00, from
  `scripts/meva_activity.py`
- `clips/`: the five dashboard clips (2018-03-12 10:40-10:45), resized to
  1280x720, from `scripts/meva_clips.py --window 10:40`. Resized from the
  original MEVA videos; otherwise unmodified.
- `../demo/<CAM-ID>.mp4`: 15-minute demo camera feeds (three consecutive clips
  from 2018-03-12 10:05, joined and resized to 1280x720) for G420, G423, G421,
  G336, G299 and G339, from `scripts/prepare_demo_feeds.py`
- `metadata/`: KF1 metadata package (site map PDF, camera list, datasheets)
  from https://mevadata.org

**Credit:** "Multiview Extended Video with Activities" (MEVA) dataset by
Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA),
https://mevadata.org

**Licence:** CC BY 4.0 (http://creativecommons.org/licenses/by/4.0/)

**Citation:** K. Corona, K. Osterdahl, R. Collins and A. Hoogs, "MEVA: A
Large-Scale Multiview, Multimodal Video Dataset for Activity Detection,"
*Proceedings of the IEEE/CVF Winter Conference on Applications of Computer
Vision (WACV)*, 2021, pp. 1060–1068.
