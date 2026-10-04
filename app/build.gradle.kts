plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.quickdrop.app"
    compileSdk = 34
    defaultConfig {
        applicationId = "com.quickdrop.app"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
}
