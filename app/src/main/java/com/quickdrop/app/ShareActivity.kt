package com.quickdrop.app

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.io.File
import java.io.IOException
import java.io.InputStream

/** Appears in the Android Share menu: pick photos/files anywhere, tap QuickDrop, they go to the laptop. */
class ShareActivity : AppCompatActivity() {

    private lateinit var info: TextView
    private lateinit var bar: ProgressBar

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(32), dp(32), dp(32), dp(32))
        }
        root.addView(TextView(this).apply { text = "Sending to laptop"; textSize = 22f })
        bar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100 }
        root.addView(bar, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(16) })
        info = TextView(this).apply { textSize = 15f; setPadding(0, dp(12), 0, 0) }
        root.addView(info)
        setContentView(root)

        val uris = collectUris()
        if (uris.isEmpty()) {
            finish()
            return
        }
        val base = Store.base(this)
        val fp = Store.fp(this)
        val cookie = Store.cookie(this)
        if (base == null || fp == null || cookie == null) {
            Toast.makeText(this, "Open QuickDrop and scan the laptop's QR code first", Toast.LENGTH_LONG).show()
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }
        Thread { sendAll(uris, base, fp, cookie) }.start()
    }

    @Suppress("DEPRECATION")
    private fun collectUris(): List<Uri> {
        val out = ArrayList<Uri>()
        if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
            val l = if (Build.VERSION.SDK_INT >= 33)
                intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
            if (l != null) out.addAll(l)
        } else {
            val u = if (Build.VERSION.SDK_INT >= 33)
                intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
            if (u != null) out.add(u)
        }
        return out
    }

    private fun ui(text: String, pct: Int) = runOnUiThread { info.text = text; bar.progress = pct }

    private fun fail(msg: String) = runOnUiThread {
        info.text = msg
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
    }

    private fun sendAll(uris: List<Uri>, base: String, fp: String, cookie: String) {
        ui("Looking for your laptop...", 0)
        val found = if (Finder.ping(base, fp)) base else Finder.find(fp)
        if (found == null) {
            fail("Laptop not found. Start QuickDrop on the laptop and connect it to this phone's hotspot.")
            return
        }
        val target: String = found
        if (target != base) Store.save(this, target, fp, cookie)
        var sent = 0
        for ((i, uri) in uris.withIndex()) {
            try {
                upload(uri, target, fp, cookie, i + 1, uris.size)
                sent++
            } catch (e: Exception) {
                fail("Failed: ${e.message}")
                return
            }
        }
        runOnUiThread {
            Toast.makeText(this, "Sent $sent file(s) to laptop", Toast.LENGTH_LONG).show()
            finish()
        }
    }

    private fun upload(uri: Uri, target: String, fp: String, cookie: String, idx: Int, total: Int) {
        var name = uri.lastPathSegment ?: "file"
        var size = -1L
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val si = c.getColumnIndex(OpenableColumns.SIZE)
                if (ni >= 0) c.getString(ni)?.let { name = it }
                if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
            }
        }
        var tmp: File? = null
        if (size <= 0) {   // size unknown: copy to cache first so the laptop gets a Content-Length
            val f = File(cacheDir, "upload.tmp")
            contentResolver.openInputStream(uri)!!.use { i -> f.outputStream().use { o -> i.copyTo(o, 1 shl 20) } }
            size = f.length()
            tmp = f
        }
        val fileName = name
        val fileSize = size
        val conn = Pin.open("$target/up", fp, cookie, 10000, 120000)
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setFixedLengthStreamingMode(fileSize)
        conn.setRequestProperty("X-Filename", Uri.encode(fileName))
        conn.setRequestProperty("Content-Type", "application/octet-stream")
        val input: InputStream = tmp?.inputStream() ?: contentResolver.openInputStream(uri)!!
        var done = 0L
        conn.outputStream.use { out ->
            input.use { inp ->
                val buf = ByteArray(1 shl 20)
                while (true) {
                    val n = inp.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    done += n
                    val pct = if (fileSize > 0) (done * 100 / fileSize).toInt() else 0
                    ui("Sending $idx/$total: $fileName", pct)
                }
            }
        }
        val code = conn.responseCode
        conn.disconnect()
        tmp?.delete()
        if (code == 401 || code == 403) throw IOException("Pairing expired - scan the QR code again")
        if (code != 200) throw IOException("HTTP $code")
    }
}
