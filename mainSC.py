import customtkinter
import json
import os

# Theme colors
mainBG = '#c8d8e4'
contrast = "#658cb1"
mnBTNHOVER = "#44698b"
mainTextColor = "#1E1E1E"
buttonBG = '#2b4257'
buttonDissabled = "#4a5158"
buttonHover = '#1b293b'
textColor = "#d0cfcf"

# Global variables
teams = []
windowWidth = 1800
windowHeight = 1000
questionTime = 4  # Timer duration in seconds
questionPhase = False

def createApp():
    app = customtkinter.CTk()
    app.geometry(str((str)(windowWidth)+'x'+(str)(windowHeight)))
    app.title("jeoParty v5?")
    #app.configure(bg_color = mainBG)
    return app

def build_grid(categories):
    """Build the game grid with the given categories"""
    if not categories or len(categories) < 6:
        print("Warning: Not enough categories, using defaults")
        categories = ["Category 1", "Category 2", "Category 3", "Category 4", "Category 5", "Category 6"]

    buttons = []
    # Create the outer frame to hold buttons and labels
    lblframe = customtkinter.CTkFrame(app) #, bg_color=mainBG, fg_color=mainBG
    lblframe.pack(padx=10, pady=(10,0), fill="x", expand=False)

    buttonFrame = customtkinter.CTkFrame(app) #, bg_color=mainBG, fg_color=mainBG
    buttonFrame.pack(fill="both", expand=True, padx=10, pady=(0,10))

    # Create category labels
    for i in range(6):
        label = customtkinter.CTkLabel(
            lblframe,
            text=categories[i],
            text_color=mainTextColor,
            #bg_color=mainBG,
            height=50,
            font=("SF Pro Display", 24, "bold"),
            width=windowWidth // 6 - 20,  # Adjust width to fit the frame
        )
        label.propagate(False)  # Prevent resizing based on content
        label.grid(row=0, column=i, padx=2, pady=2, sticky="nsew")
        lblframe.grid_columnconfigure(i, weight=1)

    # Create the buttons (rows 1-6)
    for i in range(1, 7):
        for j in range(6):
            btn = customtkinter.CTkButton(
                buttonFrame,
                text=f"{i*100}",
                fg_color=buttonBG,
                hover_color=buttonHover,
                text_color=textColor,
                font=("SF Pro Display", 32, "bold"),
            )
            btn.configure(command=lambda b=btn, c=categories[j], p=i*100: button_callback(b, c, p))
            btn.grid(row=i, column=j, padx=2, pady=2, sticky="nsew")
            buttonFrame.grid_columnconfigure(j, weight=1)
            buttons.append(btn)

        buttonFrame.grid_rowconfigure(i, weight=1)

    return buttons

def build_header():
    # Create header frame with custom styling
    height = 100
    headerFrame = customtkinter.CTkFrame(
        app,
        width=windowWidth,
        height=height,
        fg_color=contrast,  # Make frame transparent
        corner_radius=4
    )

    headerFrame.propagate(False)

    # Pack the header frame
    headerFrame.pack(side="top", fill="x", padx=10, pady=5)

    # Create and style the header label
    headerLBL = customtkinter.CTkLabel(
        headerFrame,
        height = 50,
        width = 300,  # Adjust width to fit the frame
        text="JeoParty v5?",
        text_color=mainTextColor,
        font=("SF Pro Display", 34, "bold"),
        fg_color='transparent',  # Make label background transparent
        bg_color='transparent',  # Set background color to match the header
        corner_radius=10,
    )
    headerLBL.propagate(False)  # Prevent resizing based on content
    headerLBL.pack(pady=10)

    # Create a button to see menu
    menuBTN = customtkinter.CTkButton(
        headerFrame,
        text="Menu",
        width=100,  # Adjust width to fit the frame
        command=lambda: menu_callback(headerFrame),
        fg_color='transparent',
        hover_color=mnBTNHOVER,
        text_color=mainTextColor,
        corner_radius=0
    )
    menuBTN.pack(side="bottom", padx=10, pady=(0,15))
    return headerFrame

def editheader(header,teams):
    if teams:
        header.configure(height = 150)  # Set header height
        # Destroy existing score frame if it exists
        for widget in header.winfo_children():
            if isinstance(widget, customtkinter.CTkFrame):
                widget.destroy()

        # Create a frame for team scores
        scoreFrame = customtkinter.CTkFrame(header, fg_color="transparent")
        scoreFrame.pack(side="bottom", fill="x", pady=5, before=header.winfo_children()[0])

        def edit_score(header, team_name):
            # Create pop-down frame
            edit_frame = customtkinter.CTkFrame(header, width=200, height=100, corner_radius=8)
            edit_frame.propagate(False)

            edit_frame.place(relx=0.6, rely=0.4, anchor="center")

            # Create score entry
            score_entry = customtkinter.CTkEntry(edit_frame, width=100)
            score_entry.insert(0, str([team[1] for team in teams if team[0] == team_name][0]))
            score_entry.pack(pady=5)

            def update_score():
                try:
                    new_score = int(score_entry.get())
                    for team in teams:
                        if team[0] == team_name:
                            team[1] = new_score
                    editheader(header, teams)
                    edit_frame.destroy()
                except ValueError:
                    pass

            # Create update button
            update_btn = customtkinter.CTkButton(
                edit_frame,
                text="Update",
                command=update_score,
                fg_color=buttonBG,
                hover_color=buttonHover,
                text_color=textColor
            )
            update_btn.pack(pady=5, anchor = 'center')
            update_btn.lift()

        # Add team names and scores
        for i in range(len(teams)):
            teamLabel = customtkinter.CTkButton(
                scoreFrame,
                text=f"{teams[i][0]}: {teams[i][1]}",
                text_color= textColor,
                font=("SF Pro Display", 20, "bold"),
                fg_color = "#363636",
                hover_color=mnBTNHOVER,
                command=lambda i=i: edit_score(header, teams[i][0]),
            )
            teamLabel.pack(side="left", padx=20, expand=True)
        header.pack(side="top", fill="x", padx=10, pady=5)

def menu_callback(headerframe):
    # Find all widgets named 'menuFrame'
    menu_frames = [child for child in app.winfo_children() if getattr(child, 'name', '') == 'menuFrame']

    # If menu frame exists, destroy it
    if menu_frames:
        menu_frames[0].destroy()
    else:
        # Create new menu frame if none exists
        menuFrame = customtkinter.CTkFrame(app, width=300, height=200, bg_color=buttonBG, corner_radius = 15,)
        menuFrame.name = 'menuFrame'
        #menuFrame.propagate(False)
        x = (windowWidth - 300) // 2
        y = (windowHeight - 300) // 2
        menuFrame.place(x=x, y=y, relx=0, rely=0)
        menuFrame.lift()

# team entry stuff
        team_entry = customtkinter.CTkEntry(
            menuFrame,
            placeholder_text="Enter team name",
            width=200,
            height=35,
            corner_radius=8
        )
        team_entry.pack(pady=20, padx=20)

        def add_team(headerFrame):
            team_name = team_entry.get()
            if team_name and team_name not in teams:
                teams.append([team_name,0])
                team_entry.delete(0, 'end')
                editheader(headerFrame, teams)

        add_team_btn = customtkinter.CTkButton(
            menuFrame,
            text="Add Team",
            command=lambda: add_team(headerframe),
            width=200,
            height=35,
            fg_color=buttonBG,
            hover_color=buttonHover,
            text_color=textColor
        )
        add_team_btn.pack(pady=5)

# time entry for question timer
        time_entry = customtkinter.CTkEntry(
            menuFrame,
            placeholder_text="Enter time in seconds",
            width=200,
            height=35,
            corner_radius=8
        )
        time_entry.pack(pady=20, padx=20)

        editTimebtn = customtkinter.CTkButton(
            menuFrame,
            text="Edit Time",
            command=lambda: editTime(time_entry),
            width=200,
            height=35,
            fg_color=buttonBG,
            hover_color=buttonHover,
            text_color=textColor
        )
        editTimebtn.pack(pady=10)

def changeTeamScore(header, team_name, points):
    for team in teams:
        if team[0] == team_name:
            team[1] += points
            editheader(header, teams)
            return team[1]

def getCategories():
    """Get list of categories from questions.json"""
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'questions.json')
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            categories = data.get('categories', [])
            print(f"Loaded categories: {categories}")
            return categories
    except Exception as e:
        print(f"Error loading categories: {e}")
        return ["Category 1", "Category 2", "Category 3", "Category 4", "Category 5", "Category 6"]

def getQuestions():
    """Get organized dictionary of questions by category"""
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'questions.json')
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            questions_by_category = {}
            categories = []

            # Initialize categories with empty lists
            for category in data.get('categories', []):
                questions_by_category[category] = []
                categories.append(category)

            # Add questions to their categories
            for question in data.get('questions', []):
                category_index = int(question.get('category', 1)) - 1  # Convert to 0-based index
                if 0 <= category_index < len(categories):  # Check if index is valid
                    category = categories[category_index]  # Get category name from index
                    questions_by_category[category].append({
                        'question': question.get('question', ''),
                        'answer': question.get('answer', ''),
                        'points': question.get('points', 0)
                    })

            print(f"Loaded questions for categories: {list(questions_by_category.keys())}")  # Debug print
            return questions_by_category
    except Exception as e:
        print(f"Error loading questions: {e}")
        return {}

def button_callback(button, category, points):
    global questionPhase
    questionPhase = True  # Set question phase to true when a button is clicked
    if questionPhase:
        questionFrame = customtkinter.CTkFrame(app, width=windowWidth-300, height=windowHeight-300, bg_color=mainBG, corner_radius = 15)
        questionFrame.propagate(False)
        x = (windowWidth - questionFrame.winfo_width()) // 2
        y = (windowHeight - questionFrame.winfo_height()) // 2
        questionFrame.place(relx=0.5, rely=0.5, anchor="center")
        questionFrame.lift()
        button.configure(state="disabled")  # Disable the button after it's clicked
        button.configure(fg_color=buttonDissabled)  # Change button color to indicate it's selected

        # Find the matching question based on category and points
        selected_question = None
        selected_answer = None
        for q in questions[category]:
            if q['points'] == points:
                selected_question = q['question']
                selected_answer = q['answer']
                break

        # Create label for the question
        if selected_question:
            question_display = customtkinter.CTkLabel(
                questionFrame,
                width = 1000,  # Adjust width to fit the frame
                height = 200,
                corner_radius=20,
                text=selected_question,
                text_color=mainTextColor,
                font=("SF Pro Display", 50, "bold"),
                wraplength=800,  # Set wrap length to fit the frame
                justify="center"  # Center the text

            )
            question_display.propagate(False)  # Prevent resizing based on content
            question_display.pack(pady=20)

        # Create a frame for team selection
        team_select_frame = customtkinter.CTkFrame(questionFrame, fg_color="transparent")
        team_select_frame.pack(pady=10)

        # Create buttons for each team
        for team in teams:
            team_btn = customtkinter.CTkButton(
                team_select_frame,
                text=team[0],
                fg_color=buttonBG,
                hover_color=buttonHover,
                text_color=textColor,
                command=lambda t=team[0]: show_answer_buttons(t)
            )
            team_btn.pack(side="left", padx=5)

        def show_answer_buttons(selected_team):
            global questionPhase
            if questionPhase:
                questionPhase = False  # Set question phase to false to prevent multiple clicks

                # Create and show countdown timer
                timer_label = customtkinter.CTkLabel(
                    questionFrame,
                    text=(str)(questionTime),
                    text_color=mainTextColor,
                    font=("SF Pro Display", 48, "bold"),
                    wraplength = 50
                )
                timer_label.pack(pady=20)

                def countdown(count):
                    if count > 0:
                        timer_label.configure(text=str(count))
                        questionFrame.after(1000, countdown, count-1)
                    else:
                        timer_label.destroy()
                        answer_frame.pack(pady=10)
                        answer_label.pack(pady=10)
                        right_btn.pack(side="left", padx=5)
                        wrong_btn.pack(side="left", padx=5)

                # Create frame for answer buttons
                answer_frame = customtkinter.CTkFrame(questionFrame, fg_color="transparent")


                # Show the correct answer
                answer_label = customtkinter.CTkLabel(
                    answer_frame,
                    text=f"Answer: {selected_answer}",
                    text_color=mainTextColor,
                    font=("SF Pro Display", 32),
                    wraplength = 400
                )


                # Create right/wrong buttons
                right_btn = customtkinter.CTkButton(
                    answer_frame,
                    text="Correct",
                    fg_color=buttonBG,
                    hover_color=buttonHover,
                    text_color=textColor,
                    command=lambda: handle_answer(selected_team, True, points, questionFrame)
                )


                wrong_btn = customtkinter.CTkButton(
                    answer_frame,
                    text="Wrong",
                    fg_color=buttonBG,
                    hover_color=buttonHover,
                    text_color=textColor,
                    command=lambda: handle_answer(selected_team, False, points, questionFrame)
                )
                countdown(questionTime)


        def handle_answer(team_name, is_correct, points, frame):
            if is_correct:
                changeTeamScore(header, team_name, points)
            else:
                changeTeamScore(header, team_name, -points)
            frame.destroy()
            editheader(header, teams)
            global questionPhase
            questionPhase = False

def editTime(time_entry):
    global questionTime
    questionTime = int(time_entry.get())
    time_entry.delete(0, 'end')  # Clear the entry field after setting the time

# Initialize game
catagories = getCategories()
questions = getQuestions()
app = createApp()
header = build_header()
buttons = build_grid(catagories)

app.mainloop()
