document.addEventListener('DOMContentLoaded', function () {
    const addPhoneButton = document.getElementById('add-phone');
    const phoneInput = document.getElementById('phone-input');
    const targetList = document.getElementById('target-numbers');
    
    addPhoneButton.addEventListener('click', function () {
        const phoneNumber = phoneInput.value.trim();
        if (phoneNumber && !isPhoneNumberInList(phoneNumber)) {
            // Create a new list item for the phone number
            const listItem = document.createElement('li');
            listItem.classList.add('list-group-item');
            listItem.textContent = phoneNumber;
            
            // Add a "Remove" button to the list item
            const removeButton = document.createElement('button');
            removeButton.classList.add('btn', 'btn-danger', 'btn-sm', 'ms-2');
            removeButton.textContent = 'Remove';
            removeButton.addEventListener('click', function () {
                targetList.removeChild(listItem);
            });
            
            listItem.appendChild(removeButton);
            targetList.appendChild(listItem);
            
            // Clear input field
            phoneInput.value = '';
        }
    });

    function isPhoneNumberInList(phoneNumber) {
        // Check if the phone number is already in the list
        const existingNumbers = Array.from(targetList.getElementsByTagName('li'));
        return existingNumbers.some(item => item.textContent.includes(phoneNumber));
    }

    // Before submitting the form, collect all phone numbers and set them in the hidden field
    document.querySelector('form').addEventListener('submit', function (event) {
        const phoneNumbers = Array.from(document.getElementById('target-numbers').getElementsByTagName('li'))
            .map(item => item.textContent.trim());
        
        // Set the value of the hidden field
        document.getElementById('numbers-input').value = phoneNumbers.join(',');
    });
});
function sendMessages(e) {
    e.preventDefault();
    const formData = new FormData(document.getElementById('messageForm'));
    
    fetch("{% url 'send_messages' %}", {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Messages sent successfully!');
        } else {
            alert('Error: ' + data.error);
        }
    });
}