package com.quickdrop.app

import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.MimeTypeMap
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import java.io.IOException
import javax.net.ssl.HttpsURLConnection

/** Shows the laptop's page. Tapping a laptop file downloads it and opens it right away. */
class TransferActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var bar: ProgressBar
    private lateinit var fp: String
    private lateinit var base: String
    private var chooser: ValueCallback<Array<Uri>>? = null

    private val picker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res.resultCode, res.data))
        chooser = null
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val link = intent.getStringExtra("url")
        if (link != null) {
            val u = Uri.parse(link)
            fp = (u.getQueryParameter("fp") ?: "").lowercase()
            base = "https://${u.host}:${if (u.port > 0) u.port else 8443}"
        } else {
            fp = intent.getStringExtra("fp") ?: return finish()
            base = intent.getStringExtra("base") ?: return finish()
        }

        val cm = CookieManager.getInstance()
        cm.setAcceptCookie(true)
        if (link == null) {
            Store.cookie(this)?.let { cm.setCookie(base, "$it; Secure; Path=/; Max-Age=31536000") }
        }

        web = WebView(this)
        bar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            visibility = View.GONE
        }
        val frame = FrameLayout(this)
        frame.addView(web, FrameLayout.LayoutParams(-1, -1))
        frame.addView(bar, FrameLayout.LayoutParams(-1, dp(6)))
        setContentView(frame)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.allowFileAccess = false

        web.webViewClient = object : WebViewClient() {
            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                val der = error?.certificate?.x509Certificate?.encoded
                if (der != null && Pin.sha256(der) == fp) {
                    handler?.proceed()
                } else {
                    handler?.cancel()
                    Toast.makeText(this@TransferActivity, "Security check failed: wrong device", Toast.LENGTH_LONG).show()
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
                request?.url?.host != Uri.parse(base).host

            override fun onPageFinished(view: WebView?, url: String?) {
                val ck = CookieManager.getInstance().getCookie(base)
                if (!ck.isNullOrEmpty() && Uri.parse(url ?: "").path == "/") {
                    Store.save(this@TransferActivity, base, fp, ck)
                    CookieManager.getInstance().flush()
                }
            }

            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) {
                val code = errorResponse?.statusCode ?: 0
                if (request?.isForMainFrame == true && (code == 401 || code == 403)) {
                    Store.clear(this@TransferActivity)
                    Toast.makeText(this@TransferActivity, "Pairing expired. Scan the QR code again.", Toast.LENGTH_LONG).show()
                    finish()
                }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?, cb: ValueCallback<Array<Uri>>?, params: WebChromeClient.FileChooserParams?
            ): Boolean {
                chooser?.onReceiveValue(null)
                chooser = cb
                return try {
                    picker.launch(params!!.createIntent())
                    true
                } catch (e: Exception) {
                    chooser = null
                    cb?.onReceiveValue(null)
                    false
                }
            }
        }
        web.setDownloadListener { dlUrl, _, _, _, _ -> download(dlUrl) }
        web.loadUrl(link ?: "$base/")
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    private fun toast(m: String) = runOnUiThread { Toast.makeText(this, m, Toast.LENGTH_LONG).show() }

    private fun nameOf(conn: HttpsURLConnection, url: String): String {
        val cd = conn.getHeaderField("Content-Disposition") ?: ""
        val m = Regex("filename\\*=UTF-8''([^;]+)").find(cd)
        return if (m != null) Uri.decode(m.groupValues[1]) else (Uri.parse(url).lastPathSegment ?: "file")
    }

    /** Streams into Downloads/QuickDrop with a progress bar, then opens the file. */
    private fun download(url: String) {
        toast("Downloading...")
        runOnUiThread { bar.progress = 0; bar.visibility = View.VISIBLE }
        Thread {
            try {
                val conn = Pin.open(url, fp, CookieManager.getInstance().getCookie(url), 10000, 30000)
                if (conn.responseCode != 200) throw IOException("HTTP ${conn.responseCode}")
                val name = nameOf(conn, url)
                val total = conn.contentLengthLong
                val ext = name.substringAfterLast('.', "").lowercase()
                val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, mime)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/QuickDrop")
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val dest = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw IOException("Cannot create file")
                var done = 0L
                var lastPct = -1
                contentResolver.openOutputStream(dest)!!.use { out ->
                    conn.inputStream.use { inp ->
                        val buf = ByteArray(1 shl 20)
                        while (true) {
                            val n = inp.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            done += n
                            if (total > 0) {
                                val pct = (done * 100 / total).toInt()
                                if (pct != lastPct) {
                                    lastPct = pct
                                    runOnUiThread { bar.progress = pct }
                                }
                            }
                        }
                    }
                }
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                contentResolver.update(dest, values, null, null)
                runOnUiThread {
                    bar.visibility = View.GONE
                    try {
                        startActivity(
                            Intent(Intent.ACTION_VIEW).setDataAndType(dest, mime)
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        )
                    } catch (e: ActivityNotFoundException) {
                        Toast.makeText(this, "Saved in Downloads/QuickDrop: $name (no app can open this type)", Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { bar.visibility = View.GONE }
                toast("Download failed: ${e.message}")
            }
        }.start()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
