const recordButton = document.getElementById('record');
const stopButton = document.getElementById('stop');
const audioElement = document.getElementById('audio');
const timerDisplay = document.getElementById('timer');
const responseAudio = document.getElementById('response-audio');
const questionOutput = document.getElementById('question-output');
const answerOutput = document.getElementById('answer-output');
const bookStatus = document.getElementById('book-status');

let mediaRecorder;
let audioChunks = [];
let startTime;
let timerInterval;

// Debug logging function
function logDebug(message) {
  console.log(`[DEBUG] ${message}`);
}

logDebug('Book Knowledge App script initialized');

function formatTime(time) {
  const minutes = Math.floor(time / 60).toString().padStart(2, '0');
  const seconds = Math.floor(time % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

// Book upload functionality
const bookUploadForm = document.getElementById('book-upload-form');
if (bookUploadForm) {
  bookUploadForm.addEventListener('submit', (e) => {
    const fileInput = document.getElementById('book-file');
    if (!fileInput.files.length) {
      e.preventDefault();
      alert('Please select a PDF file');
    } else {
      logDebug('Uploading book: ' + fileInput.files[0].name);
      // Form will submit normally
    }
  });
}

// Book selection functionality
const bookSelectLinks = document.querySelectorAll('.book-select');
bookSelectLinks.forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const bookFilename = link.getAttribute('data-filename');
    logDebug('Setting current book: ' + bookFilename);
    window.location.href = `/set-current-book/${bookFilename}`;
  });
});

// Recording functionality
if (recordButton) {
  logDebug('Record button found');
  
  recordButton.addEventListener('click', () => {
    // First check if a book is loaded
    if (bookStatus && bookStatus.dataset.bookLoaded !== 'true') {
      alert('Please upload or select a book first');
      return;
    }
    
    logDebug('Record button clicked');
    
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        logDebug('Microphone access granted');
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.start();
        
        audioChunks = [];
        startTime = Date.now();
        timerInterval = setInterval(() => {
          const elapsedTime = Math.floor((Date.now() - startTime) / 1000);
          timerDisplay.textContent = formatTime(elapsedTime);
        }, 1000);
        
        mediaRecorder.addEventListener('dataavailable', e => {
          logDebug('Audio data available');
          audioChunks.push(e.data);
        });
        
        mediaRecorder.addEventListener('stop', () => {
          logDebug('Recording stopped');
          clearInterval(timerInterval);
          
          const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
          const audioUrl = URL.createObjectURL(audioBlob);
          audioElement.src = audioUrl;
          
          logDebug('Creating form data for upload');
          // Create FormData and send to server
          const formData = new FormData();
          formData.append('audio_data', audioBlob, 'recorded_audio.wav');
          
          // Clear previous responses
          if (questionOutput) questionOutput.textContent = "Processing...";
          if (answerOutput) answerOutput.textContent = "";
          if (responseAudio) responseAudio.src = "";
          
          logDebug('Sending audio to server');
          fetch('/upload-question', {
            method: 'POST',
            body: formData
          })
          .then(response => {
            if (!response.ok) {
              return response.json().then(data => {
                throw new Error(data.error || 'Network response was not ok');
              });
            }
            logDebug('Server response received');
            return response.json();
          })
          .then(data => {
            logDebug('Question processed successfully');
            
            // Update UI with results
            if (questionOutput) questionOutput.textContent = data.question;
            if (answerOutput) answerOutput.textContent = data.answer;
            if (responseAudio && data.audio_url) {
              responseAudio.src = data.audio_url;
              responseAudio.play();
            }
          })
          .catch(error => {
            console.error('Error processing question:', error);
            alert('Error: ' + error.message);
            if (questionOutput) questionOutput.textContent = "Error: " + error.message;
          });
          
          // Stop all tracks in the stream
          mediaRecorder.stream.getTracks().forEach(track => track.stop());
        });
      })
      .catch(error => {
        console.error('Error accessing microphone:', error);
        alert('Could not access microphone. Please check permissions and ensure you are using HTTPS in a supported browser.');
        logDebug(`Microphone access error: ${error.name}: ${error.message}`);
      });
    
    recordButton.disabled = true;
    stopButton.disabled = false;
  });
} else {
  console.error('Record button not found in the DOM');
}

if (stopButton) {
  logDebug('Stop button found');
  
  stopButton.addEventListener('click', () => {
    logDebug('Stop button clicked');
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    
    recordButton.disabled = false;
    stopButton.disabled = true;
  });
} else {
  console.error('Stop button not found in the DOM');
}

// Initialize with disabled stop button
if (stopButton) {
  stopButton.disabled = true;
}

// Play a response audio
const playResponseButtons = document.querySelectorAll('.play-response');
playResponseButtons.forEach(button => {
  button.addEventListener('click', (e) => {
    e.preventDefault();
    const audioUrl = button.getAttribute('data-audio-url');
    if (responseAudio) {
      responseAudio.src = audioUrl;
      responseAudio.play();
    }
  });
});

// Check browser media capabilities
logDebug(`UserMedia supported: ${navigator.mediaDevices && !!navigator.mediaDevices.getUserMedia}`);
if (navigator.mediaDevices && navigator.mediaDevices.getSupportedConstraints) {
  logDebug('Supported constraints:', JSON.stringify(navigator.mediaDevices.getSupportedConstraints()));
}

// Check if we're on HTTPS
logDebug(`Page protocol: ${window.location.protocol}`);
if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
  console.warn('Media recording may require HTTPS in many browsers. Current protocol:', window.location.protocol);
}

// Log that the script has loaded correctly
logDebug('Book Knowledge App script loaded successfully');
