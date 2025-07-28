​rules_version = '2';

service cloud.firestore {
  match /databases/{database}/documents {

    // --- Helper Function to identify an admin user ---
    function isAdmin() {
      return request.auth != null && request.auth.token.email == 'admin@earnyha.com';
    }
    
    // --- Helper Function to check which fields are being changed in an update ---
    function updatedFields() {
      return request.resource.data.diff(resource.data).affectedKeys();
    }
    
    // --- Public Collection for looking up referral codes ---
    match /referralCodes/{code} {
      allow get: if request.auth != null; // Any logged-in user can check if a code exists
      allow create: if request.auth != null && request.resource.data.userId == request.auth.uid; // User can create their own code mapping
    }

    // --- Users Collection ---
    match /users/{userId} {
      // ===================================================================
      // ===== THIS IS THE CORRECTED RULE THAT FIXES THE PROBLEM =========
      // ===================================================================
      // Any logged-in user can GET a specific user's document.
      // This is needed for the referral transaction to READ the referrer's balance.
      allow get: if request.auth != null;

      // IMPORTANT: Only an ADMIN can get the LIST of all users.
      // This prevents users from scraping all other users' data.
      allow list: if isAdmin();
      
      // A user can create their own document.
      allow create: if request.auth.uid == userId;

      // Only an admin can delete a user.
      allow delete: if isAdmin();
      
      // Update rule (no changes here, it is correct)
      allow update: if
        // Condition 1: You are updating your OWN document.
        (request.auth.uid == userId) ||
        // Condition 2: You are an Admin.
        isAdmin() ||
        // Condition 3: A new user is applying a referral bonus TO THE REFERRER.
        (
          request.auth.uid != userId &&
          updatedFields().hasOnly(['balance', 'totalEarned', 'referralEarnings']) &&
          request.resource.data.balance == resource.data.balance + 5.00 &&
          request.resource.data.totalEarned == resource.data.totalEarned + 5.00 &&
          request.resource.data.referralEarnings == resource.data.referralEarnings + 5.00
        );
    }

    // --- Other Collections (No Change) ---
    match /tasks/{taskId} { allow read: if request.auth != null; allow write: if isAdmin(); }
    match /games/{gameId} { allow read: if request.auth != null; allow write: if isAdmin(); }
    match /withdrawals/{withdrawalId} { allow create: if request.auth != null; allow read, update: if isAdmin(); }
    match /users/{userId}/{collection}/{docId} { allow create: if request.auth.uid == userId; allow read: if request.auth.uid == userId || isAdmin(); }
  }
}
