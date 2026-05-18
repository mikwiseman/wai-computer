package `is`.waiwai.computer.recording

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.data.WaiApi
import java.io.File
import java.io.InputStream
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Source of the file to import, abstracted away from Android `Uri` for testability. */
interface ImportSource {
    val displayName: String
    val extension: String?
    suspend fun openInputStream(): InputStream?
}

sealed interface ImportUiState {
    data object Idle : ImportUiState
    data class Uploading(val filename: String) : ImportUiState
    data class Success(val recording: Recording) : ImportUiState
    data class Error(val message: String) : ImportUiState
}

class ImportViewModel(
    private val waiApi: WaiApi,
    private val cacheDirProvider: () -> File,
    private val language: String,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private val _uiState = MutableStateFlow<ImportUiState>(ImportUiState.Idle)
    val uiState: StateFlow<ImportUiState> = _uiState.asStateFlow()

    fun reset() {
        _uiState.value = ImportUiState.Idle
    }

    fun consumeSuccess() {
        if (_uiState.value is ImportUiState.Success) {
            _uiState.value = ImportUiState.Idle
        }
    }

    fun import(source: ImportSource) {
        if (_uiState.value is ImportUiState.Uploading) return
        val baseName = source.displayName.substringBeforeLast('.', source.displayName)
            .ifBlank { "Imported audio" }
        _uiState.value = ImportUiState.Uploading(baseName)

        viewModelScope.launch {
            var createdId: String? = null
            try {
                val cachedFile = withContext(ioDispatcher) {
                    val stream = source.openInputStream()
                        ?: throw IllegalStateException("Couldn't open the selected file.")
                    val extension = (source.extension ?: source.displayName.substringAfterLast('.', ""))
                        .lowercase()
                        .ifBlank { "audio" }
                    val target = File(cacheDirProvider(), "import-${System.currentTimeMillis()}.$extension")
                    stream.use { input ->
                        target.outputStream().use { output ->
                            input.copyTo(output)
                        }
                    }
                    target
                }

                val created = waiApi.createRecording(
                    title = baseName,
                    type = RecordingType.note,
                    language = language,
                )
                createdId = created.id

                val detail = waiApi.uploadAudio(created.id, cachedFile)
                withContext(ioDispatcher) { runCatching { cachedFile.delete() } }

                val message = detail.failureMessage?.takeIf { it.isNotBlank() }
                if (detail.status == `is`.waiwai.computer.data.RecordingStatus.Failed || message != null) {
                    _uiState.value = ImportUiState.Error(
                        message ?: "Couldn't transcribe that audio file. Please try again.",
                    )
                } else {
                    _uiState.value = ImportUiState.Success(created.copy(id = detail.id))
                }
            } catch (error: Throwable) {
                createdId?.let { id ->
                    runCatching { waiApi.deleteRecording(id, permanent = true) }
                }
                _uiState.value = ImportUiState.Error(
                    error.message ?: "Couldn't import the selected audio file.",
                )
            }
        }
    }
}
