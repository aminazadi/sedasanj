import java.net.URI
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing comes from a key.properties file kept outside the repository: either
// android/key.properties or the path in JALASE_KEY_PROPERTIES. Without it the release build falls
// back to the debug key; the update server rejects such an APK, so it can never be published.
val keyProperties = Properties().apply {
    val path = System.getenv("JALASE_KEY_PROPERTIES")
    val file = if (path.isNullOrBlank()) rootProject.file("key.properties") else File(path)
    if (file.isFile) file.inputStream().use { load(it) }
}

// FirebaseInitProvider needs these public Android resources before any Dart isolate starts.
val pushResourceNames = mapOf(
    "PUSH_FIREBASE_APP_ID" to "google_app_id",
    "PUSH_FIREBASE_API_KEY" to "google_api_key",
    "PUSH_FIREBASE_PROJECT" to "project_id",
    "PUSH_FIREBASE_SENDER_ID" to "gcm_defaultSenderId",
)
val dartDefines = (findProperty("dart-defines") as String?).orEmpty().split(",")
    .filter { it.isNotEmpty() }
    .map { String(Base64.getDecoder().decode(it), Charsets.UTF_8).split("=", limit = 2) }
    .filter { it.size == 2 }
    .associate { it[0] to it[1] }
val pushConfigured = pushResourceNames.keys.any(dartDefines::containsKey) ||
    dartDefines.containsKey("PUSH_ORIGIN")
if (pushConfigured) {
    require((pushResourceNames.keys + "PUSH_ORIGIN").all { !dartDefines[it].isNullOrBlank() }) {
        "Supply all PUSH_FIREBASE_* values and PUSH_ORIGIN for Android push."
    }
    val pushOrigin = URI(dartDefines.getValue("PUSH_ORIGIN"))
    require(pushOrigin.scheme == "https" && !pushOrigin.host.isNullOrBlank() &&
        pushOrigin.userInfo == null && pushOrigin.path.isNullOrEmpty() &&
        pushOrigin.query == null && pushOrigin.fragment == null) {
        "PUSH_ORIGIN must be a bare HTTPS origin."
    }
}

android {
    namespace = "app.jalasenegar.jalase_negar"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        if (pushConfigured) {
            pushResourceNames.forEach { (key, name) ->
                resValue("string", name, dartDefines.getValue(key))
            }
        }
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "app.jalasenegar.jalase_negar"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // One APK per channel. `direct` keeps the in-app updater; the store flavors (Bazaar, Myket)
    // drop it (see src/<flavor>/AndroidManifest.xml) because the store delivers updates.
    flavorDimensions += "store"
    productFlavors {
        create("direct") { dimension = "store" }
        create("bazaar") { dimension = "store" }
        create("myket") { dimension = "store" }
    }

    signingConfigs {
        if (keyProperties.getProperty("storeFile") != null) {
            create("release") {
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                storeFile = file(keyProperties.getProperty("storeFile"))
                storePassword = keyProperties.getProperty("storePassword")
                keyAlias = keyProperties.getProperty("keyAlias")
                keyPassword = keyProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // Keep development builds separate from the production-signed app.
            applicationIdSuffix = ".dev"
        }
        release {
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    packaging {
        resources {
            excludes += "**/libVkLayer_khronos_validation.so"
        }
        jniLibs {
            excludes += "**/x86_64/*.so"
            excludes += "**/armeabi-v7a/*.so"
        }
    }
}

dependencies {
    implementation("androidx.work:work-runtime:2.10.0")
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}

// Strip web-only assets from the APK (they come from the sherpa_onnx_web package)
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    doLast {
        val variant = name.replace("merge", "").replace("Assets", "")
        val flutterAssetsDir = layout.buildDirectory.dir("intermediates/flutter/${variant.lowercase()}/flutter_assets").get().asFile
        if (flutterAssetsDir.exists()) {
            delete(fileTree(flutterAssetsDir) {
                include("packages/sherpa_onnx_web/assets/*.wasm")
                include("packages/sherpa_onnx_web/assets/*.js")
            })
        }
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
