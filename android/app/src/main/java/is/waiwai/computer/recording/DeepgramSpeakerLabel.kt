package `is`.waiwai.computer.recording

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Pick the dominant speaker across the word array from a Deepgram diarised
 * result. Returns "speaker_<n>" (matching the backend raw_label convention)
 * or null if diarisation is off, no word carries a speaker tag, or the
 * integers are negative (treat as no signal).
 *
 * Duration-weighted: a single 2-second word from speaker 1 outweighs three
 * short words from speaker 0. Matches the Swift DeepgramSpeakerLabel helper.
 */
object DeepgramSpeakerLabel {
    fun dominant(alternative: JsonObject): String? {
        val wordsArray = alternative["words"]?.jsonArray ?: return null
        val totals = HashMap<Int, Double>()
        for (entry in wordsArray) {
            val word = entry.jsonObject
            val speaker = word["speaker"]?.jsonPrimitive?.intOrNull ?: continue
            if (speaker < 0) continue
            val start = word["start"]?.jsonPrimitive?.doubleOrNull ?: 0.0
            val end = word["end"]?.jsonPrimitive?.doubleOrNull ?: start
            val weight = maxOf(0.001, end - start)
            totals[speaker] = (totals[speaker] ?: 0.0) + weight
        }
        val winner = totals.maxByOrNull { it.value }?.key ?: return null
        return "speaker_$winner"
    }
}
