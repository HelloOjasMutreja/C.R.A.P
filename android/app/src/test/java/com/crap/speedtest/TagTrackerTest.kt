package com.crap.speedtest

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private fun tag(id: Int, side: Float = 60f) = Tag(id, FloatArray(8), side, 100f, 100f)

class TagTrackerTest {

    @Test
    fun aSingleFrameIsNotTrusted() {
        val tracker = TagTracker()

        assertEquals(emptyList<Tag>(), tracker.update(listOf(tag(17))))
    }

    @Test
    fun aMisreadThatComesAndGoesIsNeverTrusted() {
        val tracker = TagTracker()

        repeat(40) { frame ->
            val found = tracker.update(if (frame % 4 == 0) listOf(tag(17)) else emptyList())
            assertTrue(found.isEmpty())
        }
    }

    @Test
    fun aSteadyTagIsTrustedOnTheThirdFrame() {
        val tracker = TagTracker()

        tracker.update(listOf(tag(7)))
        tracker.update(listOf(tag(7)))

        assertEquals(7, tracker.update(listOf(tag(7))).single().markerId)
    }

    @Test
    fun oneMissedFrameIsForgiven() {
        val tracker = TagTracker()
        tracker.update(listOf(tag(7)))
        tracker.update(emptyList())
        tracker.update(listOf(tag(7)))

        assertEquals(1, tracker.update(listOf(tag(7))).size)
    }

    @Test
    fun aTagOutOfViewIsNotReported() {
        val tracker = TagTracker()
        repeat(4) { tracker.update(listOf(tag(7))) }

        assertTrue(tracker.update(emptyList()).isEmpty())
    }

    @Test
    fun aTagThatJumpsInSizeIsNotTrusted() {
        val tracker = TagTracker()
        tracker.update(listOf(tag(7, 30f)))
        tracker.update(listOf(tag(7, 200f)))

        assertTrue(tracker.update(listOf(tag(7, 30f))).isEmpty())
    }

    @Test
    fun differentTagsAreTrackedSeparately() {
        val tracker = TagTracker()
        tracker.update(listOf(tag(7), tag(9)))
        tracker.update(listOf(tag(7)))

        assertEquals(listOf(7), tracker.update(listOf(tag(7), tag(9))).map { it.markerId })
    }

    @Test
    fun tinyOrMisshapenDetectionsAreRejected() {
        assertTrue(plausibleTag(listOf(60f, 60f, 60f, 60f)))
        assertTrue("an angled tag is still a tag", plausibleTag(listOf(50f, 70f, 50f, 70f)))
        assertFalse("too small to read", plausibleTag(listOf(9f, 9f, 9f, 9f)))
        assertFalse("not a square", plausibleTag(listOf(30f, 90f, 30f, 90f)))
    }
}
