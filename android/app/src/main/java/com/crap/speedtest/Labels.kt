package com.crap.speedtest

data class Label(val species: String, val condition: String) {
    val healthy: Boolean get() = condition == "Healthy"
}

/** Class order must match CLASS_METADATA in vision/detector.py. */
val LABELS = listOf(
    Label("Apple", "Apple Scab"),
    Label("Apple", "Healthy"),
    Label("Apple", "Apple Rust"),
    Label("Bell Pepper", "Healthy"),
    Label("Bell Pepper", "Bacterial Spot"),
    Label("Blueberry", "Healthy"),
    Label("Cherry", "Healthy"),
    Label("Corn", "Gray Leaf Spot"),
    Label("Corn", "Leaf Blight"),
    Label("Corn", "Common Rust"),
    Label("Peach", "Healthy"),
    Label("Potato", "Healthy"),
    Label("Potato", "Early Blight"),
    Label("Potato", "Late Blight"),
    Label("Raspberry", "Healthy"),
    Label("Soybean", "Healthy"),
    Label("Squash", "Powdery Mildew"),
    Label("Strawberry", "Healthy"),
    Label("Tomato", "Early Blight"),
    Label("Tomato", "Septoria Leaf Spot"),
    Label("Tomato", "Healthy"),
    Label("Tomato", "Bacterial Spot"),
    Label("Tomato", "Late Blight"),
    Label("Tomato", "Mosaic Virus"),
    Label("Tomato", "Yellow Leaf Curl Virus"),
    Label("Tomato", "Leaf Mold"),
    Label("Tomato", "Two-spotted Spider Mite"),
    Label("Grape", "Healthy"),
    Label("Grape", "Black Rot"),
)
