package com.redclaw.jolven_flutter.rompatcher

import java.io.EOFException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.util.zip.CRC32

/** Native ROM patching primitives. This package intentionally contains no WebView or JavaScript bridge. */
enum class PatchFormat(val extensions: Set<String>) {
    IPS(setOf("ips", "ebp")), UPS(setOf("ups")), APS_N64(setOf("aps")), APS_GBA(setOf("aps")),
    BPS(setOf("bps")), RUP(setOf("rup")), PPF(setOf("ppf")), BSDIFF(setOf("bdf", "bspatch")),
    PMSR(setOf("mod")), VCDIFF(setOf("xdelta", "vcdiff"));
}

data class RomHashes(val crc32: Long, val md5: String, val sha1: String)
data class PatchInspection(val format: PatchFormat, val sourceCrc32: Long? = null, val targetCrc32: Long? = null)
data class ApplyOptions(val requireValidation: Boolean = false)

sealed interface PatchProgress { data class Copying(val bytes: Long, val total: Long) : PatchProgress; data object Complete : PatchProgress }

/** Seekable, bounds-checked binary file used by every native format parser. */
internal class BinaryFile private constructor(private val channel: FileChannel) : AutoCloseable {
    var position: Long = 0
    val size: Long get() = channel.size()
    fun seek(value: Long) { require(value in 0..size) { "Invalid patch offset" }; position = value }
    fun u8(): Int = readExact(1)[0].toInt() and 0xff
    fun u16be(): Int = ByteBuffer.wrap(readExact(2)).order(ByteOrder.BIG_ENDIAN).short.toInt() and 0xffff
    fun u24be(): Int { val b = readExact(3); return ((b[0].toInt() and 255) shl 16) or ((b[1].toInt() and 255) shl 8) or (b[2].toInt() and 255) }
    fun u32le(): Long = ByteBuffer.wrap(readExact(4)).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xffffffffL
    fun u32be(): Long = ByteBuffer.wrap(readExact(4)).order(ByteOrder.BIG_ENDIAN).int.toLong() and 0xffffffffL
    fun bytes(length: Int): ByteArray = readExact(length)
    fun readAt(offset: Long, target: ByteArray, length: Int = target.size) { channel.position(offset); readFully(target, length) }
    fun write(bytes: ByteArray) { require(position + bytes.size <= MAX_OUTPUT_BYTES) { "Patch output exceeds 96 MiB" }; channel.position(position); channel.write(ByteBuffer.wrap(bytes)); position += bytes.size }
    fun writeAt(offset: Long, bytes: ByteArray) { require(offset >= 0 && offset + bytes.size <= MAX_OUTPUT_BYTES) { "Patch writes beyond 96 MiB" }; channel.position(offset); channel.write(ByteBuffer.wrap(bytes)) }
    fun copyTo(output: BinaryFile, offset: Long = 0, count: Long = size, progress: ((PatchProgress) -> Unit)? = null) {
        val buffer = ByteArray(DEFAULT_BUFFER); var remaining = count; var source = offset
        while (remaining > 0) { val n = minOf(buffer.size.toLong(), remaining).toInt(); readAt(source, buffer, n); output.write(buffer.copyOf(n)); source += n; remaining -= n; progress?.invoke(PatchProgress.Copying(count - remaining, count)) }
    }
    private fun readExact(length: Int): ByteArray { require(length in 0..(8 * 1024 * 1024)) { "Patch record exceeds 8 MiB" }; val result = ByteArray(length); channel.position(position); readFully(result, length); position += length; return result }
    private fun readFully(target: ByteArray, length: Int) { var done = 0; while (done < length) { val n = channel.read(ByteBuffer.wrap(target, done, length - done)); if (n < 0) throw EOFException("Unexpected end of patch"); done += n } }
    override fun close() = channel.close()
    companion object {
        const val DEFAULT_BUFFER = 128 * 1024
        const val MAX_OUTPUT_BYTES = 96L * 1024 * 1024
        fun open(path: java.nio.file.Path, write: Boolean = false): BinaryFile {
            val options = if (write) arrayOf(StandardOpenOption.CREATE, StandardOpenOption.READ, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING) else arrayOf(StandardOpenOption.READ)
            return BinaryFile(FileChannel.open(path, *options))
        }
    }
}

object RomPatchEngine {
    fun hashes(path: java.nio.file.Path): RomHashes {
        val crc = CRC32(); val md5 = MessageDigest.getInstance("MD5"); val sha1 = MessageDigest.getInstance("SHA-1")
        FileChannel.open(path, StandardOpenOption.READ).use { channel -> val b = ByteBuffer.allocate(BinaryFile.DEFAULT_BUFFER); while (channel.read(b) > 0) { b.flip(); val bytes = ByteArray(b.remaining()); b.get(bytes); crc.update(bytes); md5.update(bytes); sha1.update(bytes); b.clear() } }
        fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }
        return RomHashes(crc.value, hex(md5.digest()), hex(sha1.digest()))
    }
    fun inspect(patch: java.nio.file.Path): PatchInspection = BinaryFile.open(patch).use { input ->
        val magic = input.bytes(minOf(8, input.size.toInt())).toString(Charsets.ISO_8859_1)
        when {
            magic.startsWith("PATCH") -> PatchInspection(PatchFormat.IPS)
            magic.startsWith("UPS1") -> { input.seek(input.size - 8); PatchInspection(PatchFormat.UPS, input.u32le(), input.u32le()) }
            magic.startsWith("BPS1") -> { val p = Bps.read(input); PatchInspection(PatchFormat.BPS, p.sourceCrc, p.targetCrc) }
            magic.startsWith("APS10") -> PatchInspection(PatchFormat.APS_N64)
            magic.startsWith("APSGBA") -> PatchInspection(PatchFormat.APS_GBA)
            magic.startsWith("RUP") -> PatchInspection(PatchFormat.RUP)
            magic.startsWith("PPF") -> PatchInspection(PatchFormat.PPF)
            magic.startsWith("BSDIFF40") -> PatchInspection(PatchFormat.BSDIFF)
            magic.startsWith("PMSR") -> PatchInspection(PatchFormat.PMSR)
            magic.length >= 3 && magic[0].code == 0xd6 && magic[1].code == 0xc3 && magic[2].code == 0xc4 -> PatchInspection(PatchFormat.VCDIFF)
            else -> error("Unsupported patch format")
        }
    }
    fun apply(source: java.nio.file.Path, patch: java.nio.file.Path, output: java.nio.file.Path, options: ApplyOptions = ApplyOptions(), progress: ((PatchProgress) -> Unit)? = null) {
        when (val inspection = inspect(patch)) {
            is PatchInspection -> when (inspection.format) {
                PatchFormat.IPS -> Ips.apply(source, patch, output, progress)
                PatchFormat.UPS -> Ups.apply(source, patch, output, options, progress)
                PatchFormat.BPS -> Bps.apply(source, patch, output, options, progress)
                else -> error("${inspection.format} is detected but its native decoder has not been installed")
            }
        }
        progress?.invoke(PatchProgress.Complete)
    }
}

private object Ips {
    fun apply(source: java.nio.file.Path, patch: java.nio.file.Path, output: java.nio.file.Path, progress: ((PatchProgress) -> Unit)?) {
        BinaryFile.open(source).use { rom -> BinaryFile.open(output, true).use { out -> rom.copyTo(out, progress = progress); BinaryFile.open(patch).use { p -> check(String(p.bytes(5), Charsets.ISO_8859_1) == "PATCH"); while (true) { val offsetBytes = p.bytes(3); if (String(offsetBytes, Charsets.ISO_8859_1) == "EOF") break; val offset = ((offsetBytes[0].toInt() and 255) shl 16) or ((offsetBytes[1].toInt() and 255) shl 8) or (offsetBytes[2].toInt() and 255); val length = p.u16be(); val data = if (length == 0) ByteArray(p.u16be()) { p.u8().toByte() } else p.bytes(length); out.writeAt(offset.toLong(), data) } } } }
    }
}

private object Ups {
    fun apply(source: java.nio.file.Path, patch: java.nio.file.Path, output: java.nio.file.Path, options: ApplyOptions, progress: ((PatchProgress) -> Unit)?) {
        BinaryFile.open(patch).use { p -> check(String(p.bytes(4), Charsets.ISO_8859_1) == "UPS1"); val sourceSize = vlv(p); val targetSize = vlv(p); p.seek(p.size - 12); val sourceCrc = p.u32le(); val targetCrc = p.u32le(); if (options.requireValidation) check(RomPatchEngine.hashes(source).crc32 == sourceCrc) { "Invalid input ROM checksum" }; BinaryFile.open(source).use { rom -> BinaryFile.open(output, true).use { out -> var offset = 0L; while (offset < maxOf(sourceSize, targetSize)) { val b = if (offset < sourceSize) { val one = ByteArray(1); rom.readAt(offset, one); one[0] } else 0; out.write(byteArrayOf(b)); offset++ }; offset = 0L; p.seek(4); vlv(p); vlv(p); while (p.position < p.size - 12) { offset += vlv(p); while (p.position < p.size - 12) { val xor = p.u8(); if (xor == 0) { offset++; break }; val one = ByteArray(1); if (offset < sourceSize) rom.readAt(offset, one) else one[0] = 0; one[0] = (one[0].toInt() xor xor).toByte(); out.writeAt(offset, one); offset++ } }; if (options.requireValidation) check(RomPatchEngine.hashes(output).crc32 == targetCrc) { "Patched ROM checksum mismatch" } } } }
    }
    private fun vlv(p: BinaryFile): Long { var value = 0L; var shift = 1L; while (true) { val x = p.u8(); value += (x and 0x7f) * shift; if (x and 0x80 != 0) return value; shift = shift shl 7; value += shift } }
}

private object Bps {
    data class Header(val sourceSize: Long, val targetSize: Long, val sourceCrc: Long, val targetCrc: Long)
    fun read(p: BinaryFile): Header { p.seek(0); check(String(p.bytes(4), Charsets.ISO_8859_1) == "BPS1"); val source = vlv(p); val target = vlv(p); val metadata = vlv(p); p.seek(p.position + metadata); p.seek(p.size - 12); return Header(source, target, p.u32le(), p.u32le()) }
    fun apply(source: java.nio.file.Path, patch: java.nio.file.Path, output: java.nio.file.Path, options: ApplyOptions, progress: ((PatchProgress) -> Unit)?) {
        BinaryFile.open(patch).use { p -> val h = read(p); if (options.requireValidation) check(RomPatchEngine.hashes(source).crc32 == h.sourceCrc) { "Invalid input ROM checksum" }; p.seek(4); vlv(p); vlv(p); p.seek(p.position + vlv(p)); BinaryFile.open(source).use { rom -> BinaryFile.open(output, true).use { out -> var written = 0L; var sourceRelative = 0L; var targetRelative = 0L; while (written < h.targetSize) { val action = vlv(p); val type = (action and 3).toInt(); val length = (action shr 2) + 1; require(length in 1..BinaryFile.MAX_OUTPUT_BYTES && written + length <= BinaryFile.MAX_OUTPUT_BYTES) { "Invalid BPS output length" }; when (type) { 0 -> repeat(length.toInt()) { val b = ByteArray(1); rom.readAt(written, b); out.write(b); written++ }; 1 -> { out.write(p.bytes(length.toInt())); written += length }; 2 -> { sourceRelative += signed(vlv(p)); repeat(length.toInt()) { val b=ByteArray(1); rom.readAt(sourceRelative++, b); out.write(b); written++ } }; 3 -> { targetRelative += signed(vlv(p)); repeat(length.toInt()) { val b=ByteArray(1); out.readAt(targetRelative++, b); out.write(b); written++ } } }; progress?.invoke(PatchProgress.Copying(written, h.targetSize)) }; if (options.requireValidation) check(RomPatchEngine.hashes(output).crc32 == h.targetCrc) { "Patched ROM checksum mismatch" } } } }
    }
    private fun signed(value: Long) = if (value and 1L == 0L) value shr 1 else -((value shr 1) + 1)
    private fun vlv(p: BinaryFile): Long { var value = 0L; while (true) { val x = p.u8(); value = value shl 7 or (x and 0x7f).toLong(); if (x and 0x80 != 0) return value; value++ } }
}
