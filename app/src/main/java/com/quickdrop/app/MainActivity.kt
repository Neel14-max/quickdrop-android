package com.quickdrop.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

class MainActivity : AppCompatActivity() {

    private val scanner = registerForActivityResult(ScanContract()) { r ->
        r.contents?.let { open(it) }
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
            text = "Fast, encrypted file transfer between this phone and your laptop. " +
                "No internet or mobile data needed.\n\n" +
                "1. Turn on this phone's hotspot and connect the laptop.\n" +
                "2. On the laptop run:  python quickdrop.py\n" +
                "3. Tap the button below and scan the QR code."
            textSize = 15f
            setPadding(0, dp(12), 0, dp(24))
        })
        root.addView(Button(this).apply {
            text = "Scan QR code"
            textSize = 18f
            setOnClickListener {
                scanner.launch(ScanOptions().setPrompt("Scan the QR code on your laptop")
                    .setBeepEnabled(false).setOrientationLocked(false)
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE))
            }
        }, LinearLayout.LayoutParams(-1, dp(64)))
        val link = EditText(this).apply { hint = "...or paste the full link here"; setSingleLine() }
        root.addView(link, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(32) })
        root.addView(Button(this).apply {
            text = "Connect"
            setOnClickListener { open(link.text.toString()) }
        })
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun open(raw: String) {
        val text = raw.trim()
        val u = Uri.parse(text)
        if (u.scheme != "https" || u.host.isNullOrEmpty() ||
            u.getQueryParameter("t").isNullOrEmpty() ||
            (u.getQueryParameter("fp") ?: "").length != 64) {
            Toast.makeText(this, "Not a valid QuickDrop link", Toast.LENGTH_LONG).show()
            return
        }
        startActivity(Intent(this, TransferActivity::class.java).putExtra("url", text))
    }
}
