package com.redclaw.jolven_flutter

import java.io.InputStream
import java.security.MessageDigest

/** SHA-256 digest of an explicitly selected, readable ROM document.
 * Does not unarchive, modify, or execute the file.
 */
internal object RomFingerprint {
    data class Result(val sha256: String, val size: Long)

    const val MAX_BYTES: Long = 512L * 1024L * 1024L

    fun digest(input: InputStream, maxBytes: Long = MAX_BYTES): Result {
        require(maxBytes > 0)
        val hash = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            if (count == 0) continue
            total += count
            require(total <= maxBytes) { "ROM exceeds fingerprint size limit" }
            hash.update(buffer, 0, count)
        }
        return Result(
            sha256 = hash.digest().joinToString("") { "%02x".format(it) },
            size = total
        )
    }
}
