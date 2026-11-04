"""Paper text. Every measured number is read from docs/paper/results, never typed."""

import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def load(name):
    return json.loads((RESULTS / f"{name}.json").read_text())


DATA = load("dataset")
E1 = load("e1_accuracy")
E2 = load("e2_latency")
E3 = load("e3_repeat_sighting")
E4 = load("e4_tags")
E5 = load("e5_paired_bootstrap")

SIZES = {r["imgsz"]: r for r in E1["sizes"]}
CLASSES = sorted(E1["per_class_ap50_at_800"].items(), key=lambda kv: kv[1])
TAG_HITS = sum(r["read_rate"] * r["trials"] for r in E4)
TAG_TRIALS = sum(r["trials"] for r in E4)
TAG_MIN = min(r["read_rate"] for r in E4)


def pct(x, digits=1):
    return f"{100 * x:.{digits}f}"


def interval(entry, digits=1):
    low, high = entry["ci95"]
    return f"{100 * low:.{digits}f} to {100 * high:.{digits}f}"


def main_row(method, visits, threshold=0.60):
    return next(
        r for r in E3["main"]
        if r["method"] == method and r["visits"] == visits and r["threshold"] == threshold
    )


S60, S70 = main_row("single", 1, 0.60), main_row("single", 1, 0.70)
R2, R3, R4 = main_row("repeat", 2), main_row("repeat", 3), main_row("repeat", 4)
RHO0, RHO1 = E3["correlation"][0], E3["correlation"][-1]
POOLS = E3["pools"]
N_DISEASE = len(POOLS["disease_conditions"])
N_HEALTHY = len(POOLS["healthy_species"])
POOL_IMAGES = sum(POOLS["disease_conditions"].values()) + sum(POOLS["healthy_species"].values())
TRIALS = E3["main"][0]["trials"]
BOOT = E5["settings"]

TITLE = "Repeat-Sighting Diagnosis: Longitudinal Plant Health Records for a Low-Cost Agricultural Ground Robot"
AUTHORS = "[Author names to be added]"
AFFILIATION = "[Department, Institution, City, Country] · [corresponding author email]"

ABSTRACT = (
    "Image-based plant disease detectors usually judge one photograph at a time, so a single "
    "misclassified leaf can become a diagnosis and, on a robot, a treatment. A ground robot can do "
    "something a handheld app cannot: return to the same plant. We present C.R.A.P (Crop Robotic "
    "Autonomous Platform), a low-cost software stack that keeps a persistent health record for each "
    "plant and separates what the camera saw from what the system concludes and from what the robot "
    "does. A YOLO11s detector supplies evidence only. A transparent repeat-sighting rule marks a "
    "condition as suspected after one sighting and confirmed only after it recurs at 60% confidence "
    "or higher, and spraying waits for human approval. An ordinary smartphone browser serves as "
    f"camera and display. On {DATA['images']} PlantDoc test images the detector reaches "
    f"{SIZES[640]['map50']:.3f} mAP@0.5. Passing its real detections through the engine in a "
    f"simulated three-visit protocol lowered wrong-condition diagnoses from "
    f"{pct(E5['s_wrong']['mean'])}% to {pct(E5['r_wrong']['mean'])}% at an unchanged correct-diagnosis "
    f"rate of about {pct(E5['r_true']['mean'], 0)}%. With so few test images this result is suggestive "
    f"and not conclusive: the 95% bootstrap interval for the change is "
    f"{100 * E5['diff_wrong']['ci95'][0]:.1f} to {100 * E5['diff_wrong']['ci95'][1]:.1f} percentage "
    "points. The benefit shrinks as errors become correlated between visits and disappears when each "
    "visit repeats the same view. "
    "We also show that a 480-pixel input matches 800-pixel accuracy at less than half the CPU "
    "latency. Trials on physical plants and on the assembled robot remain future work."
)

KEYWORDS = (
    "agricultural robotics, plant disease detection, object detection, YOLO, longitudinal "
    "monitoring, active perception, human-in-the-loop, precision agriculture"
)

# Block types: h1, h2, p, list, eq, fig, table. {cite:key} marks a citation.
BLOCKS = [
    ("h1", "Introduction"),
    ("p", "Pathogens and pests take a substantial share of global food production. Savary et al. "
          "estimated mean yield losses of about 21.5% for wheat, 30.0% for rice, 22.5% for maize, "
          "17.2% for potato and 21.4% for soybean, based on a global survey of crop health experts "
          "{cite:savary}. Finding disease early depends on scouting, which is slow and needs "
          "trained people. This motivates automated visual inspection."),
    ("p", "Deep learning performs very well on curated leaf images, yet this performance does not "
          "transfer easily to the field. Mohanty et al. reported 99.35% accuracy on a held-out "
          "PlantVillage test set, but only about 31% on images from other sources {cite:mohanty}. "
          "A 2025 review across 11 benchmark datasets reports 95–99% laboratory accuracy against "
          "70–85% in field deployment {cite:shafay}. A robot acting on a single prediction "
          "inherits this gap directly: one misread leaf can trigger an unnecessary treatment."),
    ("p", "Most systems treat each image as an independent question. A ground robot, however, can "
          "come back. We treat the return visit as the central design resource and ask whether a "
          "simple, explainable rule over a plant's history can reduce wrong diagnoses without "
          "retraining the detector."),
    ("p", "This paper makes the following contributions:"),
    ("list", [
        "An architecture that separates evidence, judgement and action, in which every diagnosis "
        "and action is stored with its reasons in a per-plant record.",
        "A transparent repeat-sighting rule, with a simple analytical model of how correlated "
        "errors limit it.",
        f"An evaluation that passes real detections from {DATA['images']} PlantDoc test images "
        "through the implemented engine, with image-level bootstrap intervals and a correlation "
        "stress test that exposes where the rule fails.",
        "A low-cost perception design using a smartphone browser and printed fiducial tags, with "
        "measurements showing that a 480-pixel input is the better operating point on a CPU.",
    ]),
    ("p", "We report both what the rule achieves and where it falls short. The evaluation is a "
          "trace-based simulation, not a field trial, and Section VII states what it cannot show."),

    ("h1", "Related Work"),
    ("h2", "Image-Based Plant Disease Recognition"),
    ("p", "The PlantVillage repository made large-scale leaf disease learning practical "
          "{cite:hughes}, and Mohanty et al. demonstrated high accuracy on it {cite:mohanty}. Those "
          "images are largely controlled. PlantDoc added 2,598 web-sourced images across 13 species "
          "and 27 classes, with bounding boxes, to better reflect real conditions {cite:plantdoc}. "
          "Its authors reported 38.9 mAP@0.5 with Faster R-CNN Inception-ResNet v2. Ahmad et al. "
          "studied generalization across five corn disease datasets and found that models trained "
          "on laboratory images do not reach similar accuracy in the field, with a best "
          "generalization accuracy of 81.60% {cite:ahmad}. The YOLO family reframed detection as "
          "single-pass regression {cite:redmon}, and YOLO11 refines this with C3k2 and C2PSA blocks "
          "{cite:khanam, ultralytics}."),
    ("h2", "Field Robots for Scouting and Phenotyping"),
    ("p", "AgriScout is a close recent example of a disease-scouting robot. It combines RGB "
          "cameras, RTK geotagging and a YOLOv11 model to find potato virus Y in commercial fields "
          "{cite:agriscout}. Young et al. built a low-cost tracked robot that measures individual "
          "energy sorghum plants {cite:young}. Atefi et al. note that robotic, non-destructive "
          "measurement allows traits of the same plant to be followed through a season "
          "{cite:atefi}. In a limited search we did not find a system that applies an explicit, "
          "per-plant confirmation rule to repeated disease detections; this is not a claim of "
          "priority, and a fuller survey is needed."),
    ("h2", "Multiple Views and Active Perception"),
    ("p", "Bajcsy framed perception as an active process in which a system chooses how to sense "
          "{cite:bajcsy}. Coates and Ng observed that detector errors in two images of the same "
          "scene are often different, so combining views can help, and that naively taking the "
          "strongest response can multiply false positives by the number of views {cite:coates}. "
          "They raised area under the precision-recall curve from 0.86 to 0.97 with multiple cameras "
          "and zoomed verification. They also note that correlated mistakes limit the benefit, which "
          "our stress test measures directly. Our rule uses agreement rather than the strongest "
          "response, and it does not rely on detector confidence being calibrated, a known weakness "
          "of modern networks {cite:guo}, beyond one fixed threshold."),
    ("h2", "Targeted Treatment and Safety"),
    ("p", "Spot spraying can reduce chemical use. In 25 hectares of sugarcane trials, robotic spot "
          "spraying used 35% less herbicide on average while achieving about 97% of the weed "
          "control of broadcast spraying {cite:azghadi}. These savings depend on correct targeting, "
          "so diagnosis errors matter. ISO 18497 addresses the safety of automated agricultural "
          "machinery {cite:iso}. Our approval step is a design choice in the same spirit and is not "
          "a claim of compliance."),

    ("h1", "System Overview"),
    ("p", "Fig. 1 shows the loop. A phone captures frames and displays results. A laptop runs "
          "detection and hosts the plant record, the diagnostic engine and the action manager. An "
          "ESP32 drives the robot. The modules meet only through the plant record, so each can be "
          "tested alone. This also let one software developer work in parallel with the chassis "
          "and arm teams by using a simulated robot."),
    ("fig", "architecture.png", "System loop. Detections become evidence in the plant record. The "
            "engine judges that history, and an approved action leads to a return visit that adds "
            "new evidence.", 3.45),

    ("h1", "Method"),
    ("h2", "Perception"),
    ("p", "The detector is YOLO11s {cite:khanam, ultralytics} fine-tuned on PlantDoc for 35 epochs at "
          "800-pixel input, with 9.42 M parameters and 21.5 GFLOPs. Its stored validation metrics "
          "are 0.602 mAP@0.5 and 0.423 mAP@0.5:0.95. The phone page sends 512-pixel-wide JPEG "
          "frames over a WebSocket and draws boxes over its own live video, so the video stays "
          "smooth even when detection is slower. Only one frame is in flight at a time, which "
          "prevents a queue from building. Mobile browsers allow camera access only on secure "
          "pages, so the laptop generates a self-signed certificate."),
    ("h2", "Plant Identity"),
    ("p", "A longitudinal record is useful only if the robot knows which plant it is seeing. GPS is "
          "too coarse for neighbouring plants on a low-cost robot, and visual re-identification of "
          "individual plants is difficult. We use printed ArUco markers {cite:garrido} on stakes: "
          "marker 7 maps to plant 007. The interface selects the plant when a tag is visible, with "
          "manual selection as a fallback."),
    ("h2", "Plant Record"),
    ("p", "Each plant stores observations, diagnoses and actions as durable JSON records. "
          "Observations retain the raw detections, so a changed rule can re-evaluate the original "
          "evidence. Each diagnosis stores supporting evidence, contradicting evidence and the "
          "observations it rests on. Live frames are not stored; only an operator-recorded visit "
          "enters the record."),
    ("h2", "Repeat-Sighting Rule"),
    ("p", "Let <i>s</i> be the plant's species and let <i>d</i>(<i>t</i>, <i>c</i>) be the highest "
          "confidence of condition <i>c</i> among detections of species <i>s</i> at visit <i>t</i>, "
          "considering only detections at or above a floor of 0.35. Let τ = 0.60 be the confirmation "
          "threshold, and let <i>H</i>(<i>t</i>) be the last <i>L</i> = 3 earlier visits with usable "
          "detections. Condition <i>c</i> is confirmed at visit <i>t</i> when:"),
    ("eq", r"d(t,c) \geq \tau \quad \text{and} \quad \exists\, u \in H(t):\ d(u,c) \geq \tau",
           "d(t, c) ≥ τ  and  there exists u in H(t) with d(u, c) ≥ τ"),
    ("p", "Otherwise <i>c</i> remains suspected. Detections of other species are ignored and noted, because "
          "they usually reflect a misclassification or a neighbouring plant. Healthy leaves in the "
          "same image, and earlier visits that lacked <i>c</i>, are recorded as contradicting evidence. "
          "Plant status is diseased if any condition is confirmed, suspected if any is suspected, "
          "healthy if only healthy leaves appear, and needs-reinspection if no usable leaves appear."),
    ("p", "A simple model shows what the rule can and cannot do. Suppose a healthy plant produces a "
          "false sighting with probability <i>p</i> per visit, and each visit repeats the previous view "
          "with probability ρ. The chance that two consecutive visits both produce it is:"),
    ("eq", r"P(\text{false confirmation}) = p\,[\,\rho + (1-\rho)\,p\,]",
           "P(false confirmation) = p [ ρ + (1 − ρ) p ]"),
    ("p", "With independent views (ρ = 0) the rate falls to <i>p</i>², and with identical views (ρ = 1) it "
          "stays at <i>p</i>. Repeating a sighting therefore helps only when the second look is genuinely "
          "different. This is why the closer inspection action below matters."),
    ("h2", "Environmental Context"),
    ("p", "A DHT22 sensor supplies air temperature and humidity. Disease forecasting systems for "
          "tomato and potato rely on leaf wetness and humidity {cite:rutgers}, but air humidity alone "
          "cannot diagnose disease. The engine therefore adds a note to diagnoses of "
          "humidity-favoured conditions when humidity is 70% or higher. It never creates or "
          "confirms a diagnosis. The 70% value is a provisional engineering choice."),
    ("h2", "Action Lifecycle"),
    ("p", "The action manager proposes one action per plant (Table I) and stores its reason. Nothing "
          "moves until an operator runs it, and spraying also requires explicit approval. The "
          "closer inspection links the arm to the diagnosis: it creates the second, different view "
          "that the rule needs. If any command fails, the robot is told to stop and the action is "
          "saved as failed, with the steps already completed."),
    ("table", "Proposed action for each plant status",
     ["Status", "Action", "Commands"],
     [
         ["Suspected", "Inspect closer", "Arm to inspection pose"],
         ["Diseased", "Spray (approval)", "Arm to spray pose, spray 500 ms, home"],
         ["Reinspect", "Reposition, retry", "Drive back 300 ms"],
         ["Healthy", "Move on", "Arm home, drive forward 1 s"],
     ], [0.85, 1.05, 1.6]),
    ("h2", "Robot Interface"),
    ("p", "The robot uses one ESP32 with two L298N drivers for four DC motors, a planned four-servo "
          "arm on a PCA9685 driver, and a servo that squeezes a spray bottle trigger. The laptop "
          "sends text commands over Bluetooth Classic serial. The current firmware sends no "
          "acknowledgement and silently ignores unknown commands. Arm and spray commands are not "
          "yet in the firmware, so the software refuses those steps and reports failure rather than "
          "a false success. Every move sent has a time limit of at most 3 s."),

    ("h1", "Experimental Setup"),
    ("p", f"We used the PlantDoc object detection test split {{cite:plantdoc}}: {DATA['images']} "
          f"annotated images with {DATA['boxes']} boxes, after excluding a small number of files that "
          "could not be stored on the test machine. All timing used one Intel Core Ultra 5 125H "
          "laptop CPU with no GPU, Python 3.14 and PyTorch 2.15."),
    ("p", "To test the rule without a field season, we used a trace-based simulation. We ran the "
          "detector once on every test image at 640-pixel input and cached the detections. A "
          "simulated plant is then a sequence of visits, each drawn from test images with that "
          f"plant's true label. Healthy plants used {N_HEALTHY} species pools and diseased plants used "
          f"{N_DISEASE} condition pools, covering {POOL_IMAGES} single-species images. Detections "
          "passed through the implemented engine, with the plant's species known from its tag."),
    ("p", "The baseline diagnoses a condition from a single image at the same threshold. We report "
          "three rates: correct diagnosis (the true condition is diagnosed), wrong-condition "
          "diagnosis (another condition is diagnosed on a diseased plant), and false alarm (any "
          "condition is diagnosed on a healthy plant). The engine counts a condition if it was "
          "confirmed at any visit."),
    ("p", f"Each pool holds only a few images, so simulation intervals alone would be misleadingly "
          f"narrow. For the main comparison we therefore used a paired bootstrap that resamples the "
          f"test images themselves ({BOOT['bootstraps']} resamples, {BOOT['plants_per_group']} plants "
          f"per group per resample), judging the same simulated plants with both methods. Other rows "
          f"use {TRIALS} simulated plants per group. To model correlated errors, each visit repeats "
          "the previous image with probability ρ."),

    ("h1", "Results"),
    ("h2", "Detector Accuracy and Input Size"),
    ("p", f"Table II shows accuracy and latency by input size. Accuracy is nearly flat from 480 to "
          f"800 pixels, while latency more than doubles. At 480 pixels the model reaches "
          f"{SIZES[480]['map50']:.3f} mAP@0.5 in {E2['yolo_480']['mean_ms']:.0f} ms, against "
          f"{SIZES[800]['map50']:.3f} in {E2['yolo_800']['mean_ms']:.0f} ms at 800 pixels. The "
          "difference between these accuracies is small for a test set of this size, so we read it "
          "as equivalence and not as an advantage. For live use on a CPU, 480 pixels is the better "
          "operating point."),
    ("table", "Detector accuracy and CPU latency by input size",
     ["Input (px)", "mAP@0.5", "mAP@.5:.95", "Mean (ms)", "p95 (ms)"],
     [[str(s), f"{SIZES[s]['map50']:.3f}", f"{SIZES[s]['map50_95']:.3f}",
       f"{E2[f'yolo_{s}']['mean_ms']:.0f}", f"{E2[f'yolo_{s}']['p95_ms']:.0f}"] for s in (320, 480, 640, 800)],
     [0.7, 0.7, 0.8, 0.65, 0.65]),
    ("p", f"The result of {SIZES[640]['map50']:.3f} at 640 pixels is above the stored validation "
          "value of 0.602. The exact training split is not recorded with the weights, so some overlap "
          "with these test images cannot be ruled out, and these figures may be optimistic. It is "
          "also higher than the 38.9 originally reported on PlantDoc {cite:plantdoc}, but that used "
          "an older detector and a different class setup, so the two are not directly comparable."),
    ("p", f"Fig. 2 shows large differences between classes. Average precision ranges from "
          f"{CLASSES[0][1]:.2f} for {CLASSES[0][0]} to {CLASSES[-1][1]:.2f} for {CLASSES[-1][0]}. "
          "Several visually similar tomato and potato diseases score low, which matters for the "
          "wrong-condition results below."),
    ("fig", "per_class.png", "Average precision by class at 800-pixel input on the test split. "
            "Green bars are healthy classes and red bars are diseases. Classes with few test images "
            "have high uncertainty.", 3.3),
    ("h2", "Pipeline Latency"),
    ("p", f"At the 640-pixel default, detection takes {E2['yolo_640']['mean_ms']:.0f} ms, tag reading "
          f"{E2['tag_read']['mean_ms']:.1f} ms and JPEG decoding {E2['jpeg_decode']['mean_ms']:.1f} ms "
          f"for a {E2['jpeg_kb']:.0f} KB frame. Detection therefore dominates. In an earlier end-to-end "
          "check over a local connection with the server running, the round trip averaged 166 ms, or "
          "about 6 frames per second. A browser page on the same laptop reached 3.4 to 4.7 frames per "
          "second with a simulated camera. We have not yet measured a real phone over Wi-Fi."),
    ("h2", "Repeat Sighting Against Single-Image Diagnosis"),
    ("p", f"Table III gives the main result. With three visits, wrong-condition diagnoses fell from "
          f"{pct(E5['s_wrong']['mean'])}% to {pct(E5['r_wrong']['mean'])}%, a paired change of "
          f"{100 * E5['diff_wrong']['mean']:.1f} percentage points (95% interval "
          f"{100 * E5['diff_wrong']['ci95'][0]:.1f} to {100 * E5['diff_wrong']['ci95'][1]:.1f}). "
          f"Correct diagnoses changed by {100 * E5['diff_true']['mean']:+.1f} points (interval "
          f"{100 * E5['diff_true']['ci95'][0]:.1f} to {100 * E5['diff_true']['ci95'][1]:.1f}). False "
          f"alarms changed from {pct(E5['s_false']['mean'])}% to {pct(E5['r_false']['mean'])}%, a "
          f"change of {100 * E5['diff_false']['mean']:.1f} points (interval "
          f"{100 * E5['diff_false']['ci95'][0]:.1f} to {100 * E5['diff_false']['ci95'][1]:.1f})."),
    ("p", f"These intervals call for caution. The reduction in wrong-condition diagnoses appeared in "
          f"{pct(E5['diff_wrong']['share_below_zero'], 0)}% of resamples, but its interval reaches "
          "zero, so we treat it as suggestive and not as established. The correct-diagnosis rate did "
          "not measurably change, and false alarms are too rare here to separate the two methods."),
    ("table", "Three-visit repeat sighting against one image at a 0.60 threshold (paired image bootstrap, mean and 95% interval, %)",
     ["Rate", "Single image", "Repeat sighting"],
     [
         ["Correct", f"{pct(E5['s_true']['mean'])} ({interval(E5['s_true'])})", f"{pct(E5['r_true']['mean'])} ({interval(E5['r_true'])})"],
         ["Wrong condition", f"{pct(E5['s_wrong']['mean'])} ({interval(E5['s_wrong'])})", f"{pct(E5['r_wrong']['mean'])} ({interval(E5['r_wrong'])})"],
         ["False alarm", f"{pct(E5['s_false']['mean'])} ({interval(E5['s_false'])})", f"{pct(E5['r_false']['mean'])} ({interval(E5['r_false'])})"],
     ], [1.0, 1.25, 1.25]),
    ("p", f"The number of visits sets a trade-off. Because the engine counts a confirmation at any "
          f"visit, more visits give more chances to be right and to be wrong. With {TRIALS} simulated "
          f"plants per group, two visits gave {pct(R2['true_detection_rate'])}% correct and "
          f"{pct(R2['wrong_condition_rate'])}% wrong; three gave {pct(R3['true_detection_rate'])}% and "
          f"{pct(R3['wrong_condition_rate'])}%; four gave {pct(R4['true_detection_rate'])}% and "
          f"{pct(R4['wrong_condition_rate'])}%. A confirmed wrong condition therefore does not "
          "disappear with more looking. When a detector systematically confuses two diseases, the "
          "same wrong label can recur."),
    ("p", f"Raising the single-image threshold is the obvious alternative, and Fig. 3 compares both "
          f"methods as the threshold varies. A single image at τ = 0.70 gave "
          f"{pct(S70['true_detection_rate'])}% correct and {pct(S70['wrong_condition_rate'])}% wrong. "
          "Across most of the range the repeat-sighting curve lies to the left, with fewer wrong "
          "diagnoses at a similar correct rate. The two curves come close at the extremes."),
    ("fig", "tradeoff.png", "Correct against wrong-condition diagnoses as the threshold varies from "
            "0.35 to 0.85. Up and to the left is better.", 3.3),
    ("h2", "Correlated Errors"),
    ("p", f"Fig. 4 shows the stress test. As ρ rises from 0 to 1, wrong-condition diagnoses rise from "
          f"{pct(RHO0['wrong_condition_rate'])}% to {pct(RHO1['wrong_condition_rate'])}%, and false "
          f"alarms rise from {pct(RHO0['false_alarm_rate'])}% to {pct(RHO1['false_alarm_rate'])}%. At "
          "ρ = 1 the rule performs no better than a single image, as Eq. 2 predicts. Repeat sighting "
          "is therefore only as good as the independence of its views. Note that drawing from small "
          "pools already repeats some images at ρ = 0, so even the best case here is not fully "
          "independent."),
    ("fig", "correlation.png", "Wrong-condition diagnoses as views become correlated (three visits, "
            "τ = 0.60). Error bars are 95% Wilson intervals over simulated plants.", 3.3),
    ("h2", "Plant Tags and Software Verification"),
    ("p", f"In a synthetic test, tags pasted onto leaf images with noise and optional blur were read in "
          f"{TAG_HITS:.0f} of {TAG_TRIALS:.0f} trials, with at least {pct(TAG_MIN, 0)}% in every "
          "setting from 16 to 128 pixels. Misses did not depend clearly on size, and we did not "
          "investigate their cause. This test has no perspective, shadow or dirt, so it is an upper "
          "bound on field performance."),
    ("p", "An automated suite of 83 tests passes. It covers persistence across restarts, the "
          "suspected-to-confirmed path, approval blocking, failure handling, the humidity rule and "
          "the Bluetooth command format. The Bluetooth link was tested against a simulated port."),

    ("h1", "Discussion and Limitations"),
    ("p", "The main finding is modest. A rule that needs no retraining and can be read in one line "
          "appears to reduce wrong diagnoses at the same correct rate, but the evidence is not yet "
          "conclusive, and most wrong diagnoses remain. Repeat sighting filters random errors, and it cannot "
          "correct a systematic confusion. With roughly half of diseased plants correctly diagnosed "
          "in this setting, the detector remains the larger constraint."),
    ("p", "Several limitations bound these conclusions:"),
    ("list", [
        "No field trial. Simulated visits draw different web images, not repeated views of one "
        "plant. Real revisits may be more correlated, or may show disease progressing.",
        "Small pools. Some conditions have as few as "
        f"{min(POOLS['disease_conditions'].values())} test images.",
        "Possible test overlap, since the training split is not recorded with the weights.",
        "No expert ground truth. Labels come from the dataset, not from laboratory confirmation.",
        "Domain gap. PlantDoc images come from the web and may not match this robot's camera.",
        "Hardware. The robot was not assembled and tested for this study, and arm and spray "
        "commands are not yet in the firmware. No phone-over-Wi-Fi measurement exists.",
        "Untuned thresholds. The 0.35, 0.60, three-visit and 70% humidity values are initial choices.",
        "Dependence on a laptop and a shared network, which limits field use.",
    ]),

    ("h1", "Conclusion and Future Work"),
    ("p", "We presented a low-cost plant health system that treats diagnosis as record keeping over "
          "repeated visits, not as a one-photo decision. Using real detections, a simple "
          "repeat-sighting rule showed a suggestive reduction in wrong-condition diagnoses at an "
          "unchanged correct rate, and a correlation test showed when that benefit disappears. "
          "Compared with 800 pixels, a 480-pixel input more than halved CPU latency with no "
          "measurable loss of accuracy."),
    ("p", "The next step is a controlled trial on real plants with expert labels, comparing "
          "same-view revisits with arm-driven closer views to measure real error correlation. "
          "Further work includes firmware support for the arm, a tagged-row route for autonomous "
          "visits, per-class thresholds, on-phone inference, and using low-confidence frames to "
          "retrain the model on local fields."),
]

ACK = ("The authors thank the C.R.A.P chassis, arm and perception team members. "
       "[Add funding and supervisor acknowledgements.]")

REFERENCES = {
    "savary": "S. Savary, L. Willocquet, S. J. Pethybridge, P. Esker, N. McRoberts, and A. Nelson, “The global burden of pathogens and pests on major food crops,” <i>Nature Ecology &amp; Evolution</i>, vol. 3, pp. 430–439, 2019.",
    "mohanty": "S. P. Mohanty, D. P. Hughes, and M. Salathé, “Using deep learning for image-based plant disease detection,” <i>Frontiers in Plant Science</i>, vol. 7, art. 1419, 2016.",
    "shafay": "M. Shafay, T. Hassan, M. Owais, I. Hussain, S. G. Khawaja, L. Seneviratne, and N. Werghi, “Recent advances in plant disease detection: challenges and opportunities,” <i>Plant Methods</i>, vol. 21, no. 1, art. 140, 2025.",
    "hughes": "D. P. Hughes and M. Salathé, “An open access repository of images on plant health to enable the development of mobile disease diagnostics,” arXiv:1511.08060, 2015.",
    "plantdoc": "D. Singh, N. Jain, P. Jain, P. Kayal, S. Kumawat, and N. Batra, “PlantDoc: A dataset for visual plant disease detection,” in <i>Proc. ACM CoDS-COMAD</i>, 2020, pp. 249–253.",
    "ahmad": "A. Ahmad, A. El Gamal, and D. Saraswat, “Toward generalization of deep learning-based plant disease identification under controlled and field conditions,” <i>IEEE Access</i>, vol. 11, pp. 9042–9057, 2023.",
    "redmon": "J. Redmon, S. Divvala, R. Girshick, and A. Farhadi, “You only look once: Unified, real-time object detection,” in <i>Proc. IEEE CVPR</i>, 2016, pp. 779–788.",
    "khanam": "R. Khanam and M. Hussain, “YOLOv11: An overview of the key architectural enhancements,” arXiv:2410.17725, 2024.",
    "ultralytics": "G. Jocher and J. Qiu, <i>Ultralytics YOLO11</i>, software, Ultralytics, 2024. [Online]. Available: https://github.com/ultralytics/ultralytics",
    "agriscout": "C. Singh <i>et al.</i>, “AgriScout: AI-powered robot for precise detection of PVY-infected potato plants,” <i>Computers and Electronics in Agriculture</i>, vol. 238, art. 110781, 2025.",
    "young": "S. N. Young, E. Kayacan, and J. M. Peschel, “Design and field evaluation of a ground robot for high-throughput phenotyping of energy sorghum,” <i>Precision Agriculture</i>, vol. 20, no. 4, pp. 697–722, 2019.",
    "atefi": "A. Atefi, Y. Ge, S. Pitla, and J. Schnable, “Robotic technologies for high-throughput plant phenotyping: Contemporary reviews and future perspectives,” <i>Frontiers in Plant Science</i>, vol. 12, art. 611940, 2021.",
    "bajcsy": "R. Bajcsy, “Active perception,” <i>Proceedings of the IEEE</i>, vol. 76, no. 8, pp. 966–1005, 1988.",
    "coates": "A. Coates and A. Y. Ng, “Multi-camera object detection for robotics,” in <i>Proc. IEEE ICRA</i>, 2010.",
    "guo": "C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger, “On calibration of modern neural networks,” in <i>Proc. ICML</i>, 2017, pp. 1321–1330.",
    "azghadi": "M. Rahimi Azghadi <i>et al.</i>, “Precision robotic spot-spraying: Reducing herbicide use and enhancing environmental outcomes in sugarcane,” <i>Computers and Electronics in Agriculture</i>, vol. 235, art. 110365, 2025.",
    "iso": "ISO 18497, <i>Agricultural machinery and tractors: Safety of partially automated, semi-autonomous and autonomous machinery</i>, International Organization for Standardization, 2024.",
    "garrido": "S. Garrido-Jurado, R. Muñoz-Salinas, F. J. Madrid-Cuevas, and M. J. Marín-Jiménez, “Automatic generation and detection of highly reliable fiducial markers under occlusion,” <i>Pattern Recognition</i>, vol. 47, no. 6, pp. 2280–2292, 2014.",
    "rutgers": "Rutgers Cooperative Extension, “Potato and tomato disease forecasting,” <i>Plant &amp; Pest Advisory</i>. [Online]. Available: https://plant-pest-advisory.rutgers.edu",
}
