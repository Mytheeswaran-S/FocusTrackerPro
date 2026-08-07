import cv2

print("Testing camera connection...")
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open camera.")
else:
    print("Camera opened successfully! Press 'q' on the pop-up window to exit.")
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("Error: Empty frame received!")
            break
        cv2.imshow("Camera Test Window", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()