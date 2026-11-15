allprojects {
    repositories {
        google()
        mavenCentral()
        // Store billing SDKs: Poolakey (Cafe Bazaar) is on JitPack, Myket has its own repository.
        maven { url = uri("https://jitpack.io") }
        maven { url = uri("https://maven.myket.ir") }
        maven {
            url = uri("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/")
        }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
