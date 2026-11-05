package com.crap.speedtest

private const val WINDOW_FRAMES = 4
private const val FRAMES_NEEDED = 3

// A real tag keeps about the same size between frames; a misread rarely does.
private const val MAX_SIZE_CHANGE = 1.6f

/** Below this a tag's cells are about 3 pixels wide, too small to read reliably. */
const val MIN_TAG_SIDE_PIXELS = 20f

/** A square seen at a steep angle looks stretched, but not by more than this. */
const val MAX_TAG_SIDE_RATIO = 1.6f

/** Whether a detection has the size and shape of a real tag. */
fun plausibleTag(sides: List<Float>): Boolean {
    val shortest = sides.min()
    return shortest >= MIN_TAG_SIDE_PIXELS && sides.max() / shortest <= MAX_TAG_SIDE_RATIO
}

/**
 * Trusts a tag only once it has held steady across frames. A misread in one frame could
 * otherwise send the rover driving towards nothing.
 */
class TagTracker {

    private val recent = ArrayDeque<List<Tag>>()

    /** Add a frame's tags and return those in it that are confirmed. */
    fun update(frame: List<Tag>): List<Tag> {
        recent.addLast(frame)
        if (recent.size > WINDOW_FRAMES) recent.removeFirst()
        return frame.filter(::confirmed)
    }

    private fun confirmed(tag: Tag) = recent.count { earlier ->
        earlier.any { it.markerId == tag.markerId && similarSize(it, tag) }
    } >= FRAMES_NEEDED

    private fun similarSize(a: Tag, b: Tag): Boolean {
        val ratio = a.sidePixels / b.sidePixels
        return ratio <= MAX_SIZE_CHANGE && ratio >= 1 / MAX_SIZE_CHANGE
    }
}
