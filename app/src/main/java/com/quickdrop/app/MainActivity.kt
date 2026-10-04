package com.quickdrop.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.CookieManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

class MainActivity : AppCompatActivity() {

    private lateinit var status: TextView
    private lateinit var connectBtn: Button
    private lateinit var scanBtn: Button

    private val scanner = registerForActivityResult(ScanContract()) { r ->
        r.contents?.let { pair(it) }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(48), dp(24), dp(24))
        }
        root.addView(TextView(this).apply { text = "QuickDrop"; textSize = 30f })
        root.addView(TextView(this).apply {
            text = "Encrypted file transfer to your laptop over your hotspot. No internet needed."
            textSize = 15f
            setPadding(0, dp(8), 0, dp(24))
        })
        status = TextView(this).apply { textSize = 16f; setPadding(0, 0, 0, dp(16)) }
        root.addView(status)
        connectBtn = Button(this).apply {
            text = "Connect to my laptop"
            textSize = 18f
            setOnClickListener { autoConnect() }
        }
        root.addView(connectBtn, LinearLayout.LayoutParams(-1, dp(64)))
        scanBtn = Button(this).apply {
            text = "Scan QR code (first time only)"
            setOnClickListener {
                scanner.launch(
                    ScanOptions().setPrompt("Scan the QR code in the QuickDrop window on your laptop")
                        .setBeepEnabled(false).setOrientationLocked(false)
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                )
            }
        }
        root.addView(scanBtn, LinearLayout.LayoutParams(-1, dp(56)).apply { topMargin = dp(12) })
        root.addView(Button(this).apply {
            text = "Forget laptop"
            setOnClickListener { forget() }
        }, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        root.addView(TextView(this).apply {
            text = "Tip: in your gallery or file manager, tap Share and choose QuickDrop to send " +
                "photos and files to the laptop instantly."
            textSize = 14f
            setPadding(0, dp(24), 0, 0)
        })
        setContentView(ScrollView(this).apply { addView(root) })
        if (savedInstanceState == null) autoConnect()
    }

    private fun setBusy(b: Boolean) {
        connectBtn.isEnabled = !b
        scanBtn.isEnabled = !b
    }

    /** Opens the paired laptop; searches the hotspot network if its IP changed. */
    private fun autoConnect() {
        val base = Store.base(this)
        val fp = Store.fp(this)
        if (base == null || fp == null) {
            status.text = "Not paired yet. Start QuickDrop on the laptop and scan its QR code."
            return
        }
        status.text = "Looking for your laptop..."
        setBusy(true)
        Thread {
            val target: String? = if (Finder.ping(base, fp)) base else Finder.find(fp)
            runOnUiThread {
                setBusy(false)
                if (target != null) {
                    status.text = "Connected."
                    startActivity(
                        Intent(this, TransferActivity::class.java)
                            .putExtra("base", target).putExtra("fp", fp)
                    )
                } else {
                    status.text = "Laptop not found. Open QuickDrop on the laptop, connect the laptop " +
                        "to this phone's hotspot, then tap Connect."
                }
            }
        }.start()
    }

    private fun forget() {
        Store.clear(this)
        CookieManager.getInstance().removeAllCookies(null)
        status.text = "Laptop forgotten. Scan the QR code to pair again."
    }

    private fun pair(raw: String) {
        val text = raw.trim()
        val u = Uri.parse(text)
        if (u.scheme != "https" || u.host.isNullOrEmpty() ||
            u.getQueryParameter("t").isNullOrEmpty() ||
            (u.getQueryParameter("fp") ?: "").length != 64
        ) {
            Toast.makeText(this, "Not a valid QuickDrop QR code", Toast.LENGTH_LONG).show()
            return
        }
        startActivity(Intent(this, TransferActivity::class.java).putExtra("url", text))
    }
}
