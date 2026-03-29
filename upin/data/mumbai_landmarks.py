"""
Mumbai Landmarks Database — Precise Coordinates

Additional Mumbai landmarks with high-precision coordinates
for UPIN calibration and demonstration purposes.
"""

from upin.calibration.reference_points import ReferencePoint, ReferenceType

# Additional Mumbai landmarks for demos
MUMBAI_LANDMARKS = [
    ReferencePoint(
        name="Rajabai Clock Tower",
        lat=18.928636,
        lon=72.830831,
        elevation_m=85.3,
        accuracy_m=1.0,
        reference_type=ReferenceType.LANDMARK_BUILDING,
        description="University of Mumbai Gothic Revival tower",
        survey_date="2018",
        authority="University Survey"
    ),
    ReferencePoint(
        name="Haji Ali Dargah",
        lat=18.981806,
        lon=72.809444,
        elevation_m=3.2,
        accuracy_m=2.0,
        reference_type=ReferenceType.MONUMENT,
        description="Mosque and tomb on Worli Bay",
        survey_date="2017",
        authority="Wakf Board Survey"
    ),
    ReferencePoint(
        name="Nariman Point Business District",
        lat=18.925756,
        lon=72.823264,
        elevation_m=12.1,
        accuracy_m=3.0,
        reference_type=ReferenceType.LANDMARK_BUILDING,
        description="Central business district southern tip",
        survey_date="2019",
        authority="BMC"
    ),
]
