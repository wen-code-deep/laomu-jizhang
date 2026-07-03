@ECHO OFF

::----------------------------------------------------------------------
:: Android Studio startup script.
::----------------------------------------------------------------------

:: ---------------------------------------------------------------------
:: Ensure IDE_HOME points to the directory where the IDE is installed.
:: ---------------------------------------------------------------------
SET "IDE_BIN_DIR=%~dp0"
PUSHD %IDE_BIN_DIR%
SET "IDE_BIN_DIR=%CD%"
POPD
FOR /F "delims=" %%i in ("%IDE_BIN_DIR%\..") DO SET "IDE_HOME=%%~fi"

:: ---------------------------------------------------------------------
:: Locate a JRE installation directory which will be used to run the IDE.
:: Try (in order): STUDIO_JDK, studio64.exe.jdk, ..\jbr, JDK_HOME, JAVA_HOME.
:: ---------------------------------------------------------------------
SET JRE=

IF NOT "%STUDIO_JDK%" == "" (
  IF EXIST "%STUDIO_JDK%" SET "JRE=%STUDIO_JDK%"
)

SET _JRE_CANDIDATE=
IF "%JRE%" == "" IF EXIST "%APPDATA%\Google\AndroidStudio2026.1.1\studio64.exe.jdk" (
  SET /P _JRE_CANDIDATE=<"%APPDATA%\Google\AndroidStudio2026.1.1\studio64.exe.jdk"
)
IF "%JRE%" == "" (
  IF NOT "%_JRE_CANDIDATE%" == "" IF EXIST "%_JRE_CANDIDATE%" SET "JRE=%_JRE_CANDIDATE%"
)

IF "%JRE%" == "" (
  IF EXIST "%IDE_HOME%\jbr" SET "JRE=%IDE_HOME%\jbr"
)

IF "%JRE%" == "" (
  IF EXIST "%JDK_HOME%" (
    SET "JRE=%JDK_HOME%"
  ) ELSE IF EXIST "%JAVA_HOME%" (
    SET "JRE=%JAVA_HOME%"
  )
)

SET "JAVA_EXE=%JRE%\bin\java.exe"
IF NOT EXIST "%JAVA_EXE%" (
  ECHO ERROR: cannot start Android Studio.
  ECHO No JRE found. Please make sure STUDIO_JDK, JDK_HOME, or JAVA_HOME point to a valid JRE installation.
  EXIT /B
)

:: ---------------------------------------------------------------------
:: Collect JVM options and properties.
:: ---------------------------------------------------------------------
IF NOT "%STUDIO_PROPERTIES%" == "" SET IDE_PROPERTIES_PROPERTY="-Didea.properties.file=%STUDIO_PROPERTIES%"

SET IDE_CACHE_DIR=%LOCALAPPDATA%\Google\AndroidStudio2026.1.1

:: <IDE_HOME>\bin\[win\]<exe_name>.vmoptions ...
SET VM_OPTIONS_FILE=
IF EXIST "%IDE_BIN_DIR%\studio64.exe.vmoptions" (
  SET "VM_OPTIONS_FILE=%IDE_BIN_DIR%\studio64.exe.vmoptions"
) ELSE IF EXIST "%IDE_BIN_DIR%\win\studio64.exe.vmoptions" (
  SET "VM_OPTIONS_FILE=%IDE_BIN_DIR%\win\studio64.exe.vmoptions"
)

:: ... [+ %<IDE_NAME>_VM_OPTIONS% || <IDE_HOME>.vmoptions (Toolbox) || <config_directory>\<exe_name>.vmoptions]
SET USER_VM_OPTIONS_FILE=
IF NOT "%STUDIO_VM_OPTIONS%" == "" (
  IF EXIST "%STUDIO_VM_OPTIONS%" SET "USER_VM_OPTIONS_FILE=%STUDIO_VM_OPTIONS%"
)
IF "%USER_VM_OPTIONS_FILE%" == "" (
  IF EXIST "%IDE_HOME%.vmoptions" (
    SET "USER_VM_OPTIONS_FILE=%IDE_HOME%.vmoptions"
  ) ELSE IF EXIST "%APPDATA%\Google\AndroidStudio2026.1.1\studio64.exe.vmoptions" (
    SET "USER_VM_OPTIONS_FILE=%APPDATA%\Google\AndroidStudio2026.1.1\studio64.exe.vmoptions"
  )
)

SET ACC=
SET USER_GC=
SET USER_PCT_INI=
SET USER_PCT_MAX=
SET FILTERS=%TMP%\ij-launcher-filters-%RANDOM%.txt
IF NOT "%USER_VM_OPTIONS_FILE%" == "" (
  SET ACC="-Djb.vmOptionsFile=%USER_VM_OPTIONS_FILE%"
  FINDSTR /R /C:"-XX:\+.*GC" "%USER_VM_OPTIONS_FILE%" > NUL
  IF NOT ERRORLEVEL 1 SET USER_GC=yes
  FINDSTR /R /C:"-XX:InitialRAMPercentage=" "%USER_VM_OPTIONS_FILE%" > NUL
  IF NOT ERRORLEVEL 1 SET USER_PCT_INI=yes
  FINDSTR /R /C:"-XX:M[ia][nx]RAMPercentage=" "%USER_VM_OPTIONS_FILE%" > NUL
  IF NOT ERRORLEVEL 1 SET USER_PCT_MAX=yes
) ELSE IF NOT "%VM_OPTIONS_FILE%" == "" (
  SET ACC="-Djb.vmOptionsFile=%VM_OPTIONS_FILE%"
)
IF NOT "%VM_OPTIONS_FILE%" == "" (
  IF "%USER_GC%%USER_PCT_INI%%USER_PCT_MAX%" == "" (
    FOR /F "eol=# usebackq delims=" %%i IN ("%VM_OPTIONS_FILE%") DO CALL SET ACC=%%ACC%% "%%i"
  ) ELSE (
    IF NOT "%USER_GC%" == "" ECHO -XX:\+.*GC>> "%FILTERS%"
    IF NOT "%USER_PCT_INI%" == "" ECHO -Xms>> "%FILTERS%"
    IF NOT "%USER_PCT_MAX%" == "" ECHO -Xmx>> "%FILTERS%"
    FOR /F "eol=# usebackq delims=" %%i IN (`FINDSTR /R /V /G:"%FILTERS%" "%VM_OPTIONS_FILE%"`) DO CALL SET ACC=%%ACC%% "%%i"
    DEL "%FILTERS%"
  )
)
IF NOT "%USER_VM_OPTIONS_FILE%" == "" (
  FOR /F "eol=# usebackq delims=" %%i IN ("%USER_VM_OPTIONS_FILE%") DO CALL SET ACC=%%ACC%% "%%i"
)
IF "%VM_OPTIONS_FILE%%USER_VM_OPTIONS_FILE%" == "" (
  ECHO ERROR: cannot find a VM options file
)

SET "ARG_FILE=%TMP%\ij-launcher-%RANDOM%%RANDOM%.tmp"

ECHO|SET /P="-cp " > "%ARG_FILE%"

ECHO|SET /P=""%IDE_HOME:\=/%/lib/platform-loader.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/util-8.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/app.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/util.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/app-backend.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/annotations.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/eclipse.lsp4j.debug.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/eclipse.lsp4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/eclipse.lsp4j.jsonrpc.debug.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/eclipse.lsp4j.jsonrpc.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/external-system-rt.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/externalProcess-rt.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.andel.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.bifurcan.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.fastutil.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.kernel.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.multiplatform.shims.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.reporting.api.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.reporting.shared.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.rhizomedb.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.rhizomedb.transactor.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.rhizomedb.transactor.rebase.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.rpc.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.rpc.server.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.util.codepoints.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.util.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.util.logging.api.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/fleet.util.serialization.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/forms_rt.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/groovy.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/idea_rt.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij-test-discovery.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.aalto.xml.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.asm.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.asm.tools.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.automaton.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.batik.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.blockmap.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.bouncy.castle.pgp.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.bouncy.castle.provider.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.caffeine.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.cglib.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.classgraph.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.cli.parser.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.cli.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.codec.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.compress.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.imaging.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.io.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.lang3.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.commons.logging.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.fastutil.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.gson.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.guava.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.hash4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.hdr.histogram.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.http.client.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.icu4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.imgscalr.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ini4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ion.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jackson.databind.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jackson.dataformat.yaml.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jackson.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jackson.jr.objects.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jackson.module.kotlin.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.java.websocket.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.javax.annotation.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jaxen.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jbr.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jcef.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jcip.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jediterm.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jediterm.ui.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jettison.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jgoodies.common.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jgoodies.forms.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jsonpath.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jsoup.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jsvg.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jvm.native.trusted.roots.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.jzlib.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlin.reflect.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.collections.immutable.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.coroutines.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.coroutines.debug.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.coroutines.slf4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.datetime.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.html.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.io.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.serialization.cbor.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.serialization.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.serialization.json.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kotlinx.serialization.protobuf.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.kryo5.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.client.cio.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.client.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.io.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.network.tls.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.server.cio.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.ktor.utils.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.lz4.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.markdown.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.miglayout.swing.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.mvstore.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.netty.buffer.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.netty.codec.compression.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.netty.codec.http.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.netty.handler.proxy.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.opentelemetry.exporter.sender.jdk.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.opentelemetry.sdk.autoconfigure.spi.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.oro.matcher.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.protobuf.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.proxy.vole.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.pty4j.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.rd.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.rd.framework.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.rd.swing.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.rd.text.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.rhino.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.snakeyaml.engine.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.snakeyaml.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.sshj.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.stream.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.swingx.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.velocity.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.winp.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.xerces.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.xstream.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.xtext.xbase.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.libraries.xz.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.analysis.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.analysis.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.builtInServer.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.builtInServer.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.core.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.core.ui.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.credentialStore.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.credentialStore.ui.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.debugger.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.debugger.impl.rpc.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.debugger.impl.shared.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.debugger.impl.ui.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.debugger.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.diff.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.diff.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.duplicates.analysis.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.eel.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.externalProcessAuthHelper.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.externalSystem.dependencyUpdater.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.externalSystem.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.externalSystem.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.find.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.ide.concurrency.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.ide.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.ide.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.ide.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.kernel.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.lang.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.lang.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.lang.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.locking.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.managed.cache.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.polySymbols.backend.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.polySymbols.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.projectFrame.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.projectModel.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.projectModel.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.rpc.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.rpc.topics.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.scopes.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.smRunner.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.util.ex.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.util.ui.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.vcs.core.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.vcs.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.vcs.shared.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.welcomeScreen.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.platform.welcomeScreen.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.regexp.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.analysis.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.analysis.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.dom.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.dom.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.parser.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.psi.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.psi.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.structureView.impl.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.structureView.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.syntax.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/intellij.xml.ui.common.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/javax.activation.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/javax.annotation-api.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/jaxb-api.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/jaxb-runtime.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/jps-model.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/junit4.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/kotlinx-coroutines-guava.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/lib.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/opentelemetry.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/rd-gen.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/resources.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/stats.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/trove.jar";" >> "%ARG_FILE%"
ECHO|SET /P=""%IDE_HOME:\=/%/lib/util_rt.jar";" >> "%ARG_FILE%"

:: ---------------------------------------------------------------------
:: Run the IDE.
:: ---------------------------------------------------------------------
"%JAVA_EXE%" ^
  @"%ARG_FILE%" ^
  "-XX:ErrorFile=%USERPROFILE%\java_error_in_studio_%%p.log" ^
  "-XX:HeapDumpPath=%USERPROFILE%\java_error_in_studio.hprof" ^
  %ACC% ^
  %IDE_PROPERTIES_PROPERTY% ^
  "-Xbootclasspath/a:%IDE_HOME%\lib\nio-fs.jar" -Djava.system.class.loader=com.intellij.util.lang.PathClassLoader -Didea.vendor.name=Google -Didea.paths.selector=AndroidStudio2026.1.1 "-Djna.boot.library.path=%IDE_HOME%/lib/jna/amd64" -Djna.nosys=true -Djna.noclasspath=true "-Dpty4j.preferred.native.folder=%IDE_HOME%/lib/pty4j" -Dio.netty.allocator.type=pooled "-Dskiko.library.path=%IDE_HOME%/lib/skiko-awt-runtime-all" "-Dintellij.platform.runtime.repository.path=%IDE_HOME%/modules/module-descriptors.dat" -Didea.platform.prefix=AndroidStudio -XX:FlightRecorderOptions=stackdepth=256 --add-opens=java.base/sun.net.www.protocol.https=ALL-UNNAMED -Djava.security.manager=allow -XX:CompileCommand=exclude,org.jetbrains.kotlin.serialization.deserialization.TypeDeserializer::simpleType -XX:CompileCommand=exclude,org.jetbrains.kotlin.serialization.deserialization.TypeDeserializer::toAttributes -Dsplash=true -Daether.connector.resumeDownloads=false -Dcompose.swing.render.on.graphics=true --enable-native-access=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.lang.ref=ALL-UNNAMED --add-opens=java.base/java.lang.reflect=ALL-UNNAMED --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/java.nio.charset=ALL-UNNAMED --add-opens=java.base/java.text=ALL-UNNAMED --add-opens=java.base/java.time=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/java.util.concurrent=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.locks=ALL-UNNAMED --add-opens=java.base/jdk.internal.ref=ALL-UNNAMED --add-opens=java.base/jdk.internal.vm=ALL-UNNAMED --add-opens=java.base/sun.net.dns=ALL-UNNAMED --add-opens=java.base/sun.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/sun.nio.fs=ALL-UNNAMED --add-opens=java.base/sun.security.ssl=ALL-UNNAMED --add-opens=java.base/sun.security.util=ALL-UNNAMED --add-opens=java.desktop/com.sun.java.swing=ALL-UNNAMED --add-opens=java.desktop/java.awt=ALL-UNNAMED --add-opens=java.desktop/java.awt.dnd.peer=ALL-UNNAMED --add-opens=java.desktop/java.awt.event=ALL-UNNAMED --add-opens=java.desktop/java.awt.font=ALL-UNNAMED --add-opens=java.desktop/java.awt.image=ALL-UNNAMED --add-opens=java.desktop/java.awt.peer=ALL-UNNAMED --add-opens=java.desktop/javax.swing=ALL-UNNAMED --add-opens=java.desktop/javax.swing.plaf.basic=ALL-UNNAMED --add-opens=java.desktop/javax.swing.text=ALL-UNNAMED --add-opens=java.desktop/javax.swing.text.html=ALL-UNNAMED --add-opens=java.desktop/javax.swing.text.html.parser=ALL-UNNAMED --add-opens=java.desktop/sun.awt=ALL-UNNAMED --add-opens=java.desktop/sun.awt.datatransfer=ALL-UNNAMED --add-opens=java.desktop/sun.awt.image=ALL-UNNAMED --add-opens=java.desktop/sun.awt.windows=ALL-UNNAMED --add-opens=java.desktop/sun.font=ALL-UNNAMED --add-opens=java.desktop/sun.java2d=ALL-UNNAMED --add-opens=java.desktop/sun.swing=ALL-UNNAMED --add-opens=java.management/sun.management=ALL-UNNAMED --add-opens=jdk.attach/sun.tools.attach=ALL-UNNAMED --add-opens=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED --add-opens=jdk.internal.jvmstat/sun.jvmstat.monitor=ALL-UNNAMED --add-opens=jdk.jdi/com.sun.tools.jdi=ALL-UNNAMED ^
  com.android.tools.idea.MainWrapper ^
  %*

DEL "%ARG_FILE%" > NUL
